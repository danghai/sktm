# Copyright (c) 2017 Red Hat, Inc. All rights reserved. This copyrighted
# material is made available to anyone wishing to use, modify, copy, or
# redistribute it subject to the terms and conditions of the GNU General
# Public License v.2 or later.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

from __future__ import print_function
import datetime
import dateutil.parser
import email
import email.header
import enum
import json
import logging
import requests
import re
import urllib
import xmlrpclib
import sktm


class PatchsetSummary(object):
    """A patchset summary"""

    def __init__(self, message_id, subject, email_addr_set, patch_url_list):
        """
        Initialize a patchset summary.

        Args:
            message_id:     Value of the "Message-Id" header of the e-mail
                            message representing the patchset.
            subject:        Subject of the message representing the patchset.
            email_addr_set: A set of e-mail addresses involved with the
                            patchset.
            patch_url_list: A list of URLs pointing to Patchwork patch
                            objects comprising the patchset, in order they
                            should be applied in.
        """
        # Message-Id of the message representing the patchset
        self.message_id = message_id
        # Subject of the message representing the patchset
        self.subject = subject
        # A set of e-mail addresses involved with the patchset
        self.email_addr_set = email_addr_set
        # A list of URLs pointing to Patchwork patch objects comprising
        # the patchset
        self.patch_url_list = patch_url_list


# TODO Move common code to a common parent class

# TODO Supply this on Patchwork instance creation instead
SKIP_PATTERNS = [
    r"\[[^\]]*iproute.*?\]",
    r"\[[^\]]*pktgen.*?\]",
    r"\[[^\]]*ethtool.*?\]",
    r"\[[^\]]*git.*?\]",
    r"\[[^\]]*pull.*?\]",
    r"pull.?request"
]


def stringify(v):
    """Convert any value to a str object

    xmlrpc is not consistent: sometimes the same field
    is returned a str, sometimes as unicode. We need to
    handle both cases properly.
    """
    if isinstance(v, unicode):
        return v.encode('utf-8')

    return str(v)


# Internal RH PatchWork adds a magic API version with each call
# this class just magically adds/removes it
class RpcWrapper:
    def __init__(self, real_rpc):
        self.rpc = real_rpc
        # patchwork api coded to
        self.version = 1010

    def _wrap_call(self, rpc, name):
        # Wrap a RPC call, adding the expected version number as argument
        fn = getattr(rpc, name)

        def wrapper(*args, **kwargs):
            return fn(self.version, *args, **kwargs)
        return wrapper

    def _return_check(self, r):
        # Returns just the real return value, without the version info.
        v = self.version
        if r[0] != v:
            raise RpcProtocolMismatch('Patchwork API mismatch (%i, '
                                      'expected %i)' % (r[0], v))
        return r[1]

    def _return_unwrapper(self, fn):
        def unwrap(*args, **kwargs):
            return self._return_check(fn(*args, **kwargs))
        return unwrap

    def __getattr__(self, name):
        # Add the RPC version checking call/return wrappers
        return self._return_unwrapper(self._wrap_call(self.rpc, name))


class pwresult(enum.IntEnum):
    """Patchwork state codes"""
    PENDING = 0
    SUCCESS = 1
    WARNING = 2
    FAILURE = 3


class skt_patchwork2(object):
    """
    A Patchwork REST interface
    """
    def __init__(self, baseurl, projectname, since, apikey=None):
        """
        Initialize a Patchwork REST interface.

        Args:
            baseurl:        Patchwork base URL.
            projectname:    Patchwork project name, or None.
            since:          Last processed patch timestamp in a format
                            accepted by dateutil.parser.parse. Patches with
                            this or earlier timestamp will be ignored.
            apikey:         Patchwork API authentication token.
        """
        # Base Patchwork URL
        self.baseurl = baseurl
        # Last processed patch timestamp in a dateutil.parser.parse format
        self.since = since
        # TODO Describe
        self.nsince = None
        # Patchwork API authentication token.
        self.apikey = apikey
        # JSON representation of API URLs retrieved from the Patchwork server
        self.apiurls = self.get_apiurls()
        # A regular expression matching names of the patches to skip
        self.skp = re.compile("%s" % "|".join(SKIP_PATTERNS), re.IGNORECASE)
        # JSON representation of the specified project (if any), retrieved
        # from the Patchwork server
        self.project = None

        if projectname is not None:
            self.project = self.get_project(projectname)

    # TODO Convert this to a simple function
    @property
    def projectid(self):
        return int(self.project.get("id"))

    # TODO Convert this to a simple function
    @property
    def newsince(self):
        return self.nsince.isoformat() if self.nsince else None

    # FIXME Rename to use a verb
    def patchurl(self, patch):
        """
        Retrieve a patch URL from a JSON patch object.

        Args:
            patch:  The JSON patch object to get URL from.

        Returns:
            URL of the patch.
        """
        return "%s/patch/%d" % (self.baseurl, patch.get("id"))

    def get_project(self, pname):
        """
        Retrieve JSON representation of the specified project from the
        Patchwork server.

        Args:
            pname:  The name of the project to retrieve.

        Returns:
            The JSON representation of the specified project.
        """
        r = requests.get("%s/%s" % (self.apiurls.get("projects"), pname))
        if r.status_code != 200:
            raise Exception("Can't get project data: %s %d" % (pname,
                            r.status_code))
        return r.json()

    def get_apiurls(self):
        """
        Retrieve JSON representation of the list of API URLs supported by the
        Patchwork server.

        Returns:
            The JSON representation of the API URLs.
        """
        r = requests.get("%s/api" % self.baseurl)
        if r.status_code != 200:
            raise Exception("Can't get apiurls: %d" % r.status_code)

        return r.json()

    def get_header_value(self, patch_id, *keys):
        """
        Get the value(s) of requested message headers.

        Since Patchwork 2.1, all the headers with same key are returned in the
        API as a list (this is relevant for eg. 'Received' header which can be
        present multiple times; before, only one of them was present). Work
        around this difference by concatenating the values with double newlines
        as a divider (we shouldn't need headers which can be present multiple
        times anyways).

        Args:
            patch_id: ID of the patch to retrieve header value for.
            keys:     Keys of the headers which values should be retrieved.

        Returns:
            A tuple of strings representing the values of requested headers
            from patch.
        """
        req = requests.get('%s/%s' % (self.apiurls.get('patches'), patch_id))

        if req.status_code != 200:
            raise Exception('Failed to get data for patch %d (%d)' %
                            (patch_id, req.status_code))

        res = ()
        headers = {}
        # Make sure we handle case difference until we switch to mbox parsing
        for key, value in req.json().get('headers', {}).items():
            headers[key.lower()] = value

        for key in keys:
            value = headers.get(key.lower(), '')
            # We need to handle strings and unicode.
            # NOTE: basestring doesn't exist in PY3 but since the retrieval
            # will be reworked before we get compatible it shouldn't matter
            if isinstance(value, basestring):
                res += (value,)
            else:
                res += ('\n\n'.join([val for val in value]),)

        return res

    def get_emails(self, pid):
        """
        Get all involved e-mail addresses from patch message headers.

        Args:
            pid:    ID of the patch to get emails for.

        Returns:
            A set of e-mail addresses involved with the patch.
        """
        emails = set()

        logging.debug("getting emails for patch %d from 'from', 'to', 'cc'")
        header_values = self.get_header_value(pid, "from", "to", "cc")
        for header_value in header_values:
            for faddr in [x.strip() for x in header_value.split(",") if x]:
                logging.debug("patch=%d; email=%s", pid, faddr)
                maddr = re.search(r"\<([^\>]+)\>", faddr)
                if maddr:
                    emails.add(maddr.group(1))
                else:
                    emails.add(faddr)

        return emails

    def get_series_from_url(self, url):
        """
        Retrieve a list of applicable (non-skipped) patchset summaries
        for the specified patch series, or patch series list URL.
        TODO Describe skipping criteria.

        Args:
            url:    The patch series, or patch series list URL to retrieve
                    patchset summaries for.

        Returns:
            A list of patchset summaries.
        """
        patchsets = list()

        logging.debug("get_series_from_url %s", url)
        r = requests.get(url)

        if r.status_code != 200:
            raise Exception("Can't get series from url %s (%d)" % (url,
                            r.status_code))

        sdata = r.json()
        # If there is a single series returned we get a dict, not a list with
        # a single element. Fix this inconsistency for easier processing.
        if not isinstance(sdata, list):
            sdata = [sdata]

        for series in sdata:
            message_id = None
            subject = None
            all_emails = set()
            plist = list()

            if not series.get("received_all"):
                logging.info("skipping incomplete series: [%d] %s",
                             series.get("id"), series.get("name"))
                continue

            if self.skp.search(series.get("name")):
                logging.info("skipping series %d: %s", series.get("id"),
                             series.get("name"))
                continue

            logging.info("series [%d] %s", series.get("id"),
                         series.get("name"))

            for patch in series.get("patches"):
                logging.info("patch [%d] %s", patch.get("id"),
                             patch.get("name"))
                plist.append(self.patchurl(patch))
                message_id, subject = self.get_header_value(patch.get("id"),
                                                            'Message-ID',
                                                            'Subject')
                emails = self.get_emails(patch.get("id"))
                logging.debug("patch [%d] message_id: %s", patch.get("id"),
                              message_id)
                logging.debug("patch [%d] subject: %s", patch.get("id"),
                              subject)
                logging.debug("patch [%d] emails: %s", patch.get("id"),
                              emails)
                all_emails = all_emails.union(emails)
            logging.info("---")

            if plist:
                logging.debug("series [%d] message_id: %s", series.get("id"),
                              message_id)
                logging.debug("series [%d] subject: %s", series.get("id"),
                              subject)
                logging.debug("series [%d] emails: %s", series.get("id"),
                              all_emails)
                patchsets.append(PatchsetSummary(message_id,
                                                 subject,
                                                 all_emails,
                                                 plist))

        link = r.headers.get("Link")
        if link is not None:
            m = re.match("<(.*)>; rel=\"next\"", link)
            if m:
                nurl = m.group(1)
                # TODO Limit recursion
                patchsets += self.get_series_from_url(nurl)

        return patchsets

    def get_patchsets_from_events(self, url):
        """
        Retrieve a list of applicable (non-skipped) patchset summaries for the
        specified event list URL.

        Args:
            url:    The event list URL to retrieve patchset summaries for.

        Returns:
            A list of patchset summaries.
        """
        patchsets = list()

        logging.debug("get_patchsets_from_events: %s", url)
        r = requests.get(url)

        if r.status_code != 200:
            raise Exception("Can't get events from url %s (%d)" % (url,
                            r.status_code))

        edata = r.json()
        # If there is a single event returned we get a dict, not a list with
        # a single element. Fix this inconsistency for easier processing.
        if not isinstance(edata, list):
            edata = [edata]

        # For each event
        for event in edata:
            # TODO Are these the only possible events?
            series = event.get("payload", {}).get("series")
            if series is None:
                continue

            edate = dateutil.parser.parse(event.get("date"))
            if self.nsince is None or self.nsince < edate:
                self.nsince = edate

            patchsets += self.get_series_from_url(series.get("url"))

        link = r.headers.get("Link")
        if link is not None:
            m = re.match("<(.*)>; rel=\"next\"", link)
            if m:
                nurl = m.group(1)
                # TODO Limit recursion
                patchsets += self.get_patchsets_from_events(nurl)

        return patchsets

    def _set_patch_check(self, patch, payload):
        """
        Add a patch "check" payload for the specified JSON representation of a
        patch.

        Args:
            patch:      JSON representation of a patch to add the check for.
            payload:    The "check" payload dictionary to be converted to JSON.
        """
        r = requests.post(patch.get("checks"),
                          headers={"Authorization": "Token %s" % self.apikey,
                                   "Content-Type": "application/json"},
                          data=json.dumps(payload))

        if r.status_code not in [200, 201]:
            logging.warning("Failed to post patch check: %d" % r.status_code)

    def set_patch_check(self, pid, jurl, result):
        """
        Add a patch "check" for the specified patch, with the specified
        Jenkins build URL and result (sktm.tresult).

        Args:
            pid:    The ID of the patch to add the "check" for.
            jurl:   Jenkins build URL for the "check" to reference.
            result: Test result (sktm.tresult) to feature in the "check"
                    state.
        """
        if self.apikey is None:
            logging.debug("No patchwork api key provided, not setting checks")
            return

        payload = {'patch': pid,
                   'state': None,
                   'target_url': jurl,
                   'context': 'skt',
                   'description': 'skt boot test'}
        if result == sktm.tresult.SUCCESS:
            payload['state'] = int(pwresult.SUCCESS)
        elif result == sktm.tresult.BASELINE_FAILURE:
            payload['state'] = int(pwresult.WARNING)
            payload['description'] = 'Baseline failure found while testing '
            'this patch'
        else:
            payload['state'] = int(pwresult.FAILURE)
            payload['description'] = str(result)

        self._set_patch_check(self.get_patch_by_id(pid), payload)

    def get_patch_by_id(self, pid):
        """
        Retrieve a patch object by patch ID.

        Args:
            pid:    ID of the patch to retrieve.

        Returns:
            Parsed JSON object as described in
            https://patchwork-freedesktop.readthedocs.io/en/latest/rest.html#patches
        """
        r = requests.get("%s/%d" % (self.apiurls.get("patches"), pid))

        if r.status_code != 200:
            raise Exception("Can't get patch by id %d (%d)" % (pid,
                            r.status_code))

        return r.json()

    def get_patchsets_by_patch(self, url, db=None, seen=set()):
        """
        Retrieve a list of summaries of patchsets, which weren't already
        "seen", and which contain the patch or patches available at the
        specified URL.

        Args:
            url:    The URL pointing to a patch or a patch list to retrieve
                    the list of patch series from.
            db:     The optional database interface to retrieve "tested"
                    status for the patch series from.
            seen:   A set of IDs of patch series which should be ignored, and
                    which should have patch series IDs added once they're
                    processed.

        Returns:
            A list of patchset summaries.
        """
        patchsets = list()

        logging.debug("get_patchsets_by_patch %s", url)
        r = requests.get(url)

        if r.status_code != 200:
            raise Exception("Can't get series from url %s (%d)" % (url,
                            r.status_code))

        pdata = r.json()
        # If there is a single patch returned we get a dict, not a list with
        # a single element. Fix this inconsistency for easier processing.
        if type(pdata) is not list:
            pdata = [pdata]

        for patch in pdata:
            # For each patch series the patch belongs to
            for series in patch.get("series"):
                sid = series.get("id")
                if (sid in seen):
                    continue
                elif db and db.get_series_result(sid):
                    logging.info("skipping already tested series: [%d] %s",
                                 sid, series.get("name"))
                    continue
                else:
                    patchsets += self.get_series_from_url("%s/%d" % (
                        self.apiurls.get("series"),
                        sid
                    ))
                    seen.add(sid)

        link = r.headers.get("Link")
        if link:
            m = re.match("<(.*)>; rel=\"next\"", link)
            if m:
                nurl = m.group(1)
                # TODO Limit recursion
                patchsets += self.get_patchsets_by_patch(nurl, db, seen)

        return patchsets

    def get_new_patchsets(self):
        """
        Retrieve a list of summaries of applicable (non-skipped) patchsets.

        Returns:
            A list of patchset summaries.
        """
        # TODO Figure out if adding a second is right here, since the API doc
        # at https://patchwork-freedesktop.readthedocs.io/en/latest/rest.html
        # says regarding "since" query parameter:
        #
        #   Retrieve only events newer than a specific time. Format is the
        #   same as event_time in response, an ISO 8601 date. That means that
        #   the event_time from the last seen event can be used in the next
        #   query with a since parameter to only retrieve events that haven't
        #   been seen yet.
        nsince = dateutil.parser.parse(
            self.since
        ) + datetime.timedelta(seconds=1)

        logging.debug("get_new_patchsets since %s", nsince.isoformat())
        patchsets = self.get_patchsets_by_patch("%s?project=%d&since=%s" %
                                                (self.apiurls.get("patches"),
                                                 self.projectid,
                                                 urllib.quote(
                                                     nsince.isoformat()
                                                 )))
        return patchsets

    # TODO This shouldn't really skip patches to retrieve, should it?
    def get_patchsets(self, patchlist):
        """
        Retrieve a list of summaries of applicable (non-skipped) patchset for
        the specified list of patch IDs.

        Args:
            patchlist:  List of patch IDs to retrieve patchset summaries for,
                        or skip over.

        Returns:
            A list of patchset summaries.
        """
        patchsets = list()
        seen = set()

        logging.debug("get_patchsets: %s", patchlist)
        # For each patch ID
        for pid in patchlist:
            patch = self.get_patch_by_id(pid)
            if patch:
                # For each series the patch belongs to
                for series in patch.get("series"):
                    sid = series.get("id")
                    if sid not in seen:
                        patchsets += self.get_series_from_url("%s/%d" % (
                            self.apiurls.get("series"),
                            sid
                        ))
                        seen.add(sid)

        return patchsets


class skt_patchwork(object):
    """
    A Patchwork XML RPC interface
    """
    def __init__(self, baseurl, projectname, lastpatch):
        """
        Initialize a Patchwork XML RPC interface.

        Args:
            baseurl:        Patchwork base URL.
            projectname:    Patchwork project name, or None.
            lastpatch:      Maximum processed patch ID to start with.
        """
        self.fields = None
        # XML RPC interface to Patchwork
        self.rpc = self.get_rpc(baseurl)
        # Base Patchwork URL
        self.baseurl = baseurl
        # ID of the project, if project name is supplied, otherwise None
        self.projectid = self.get_projectid(
            projectname
        ) if projectname else None
        # Maximum processed patch ID
        self.lastpatch = lastpatch
        # A regular expression matching names of the patches to skip
        self.skp = re.compile("%s" % "|".join(SKIP_PATTERNS), re.IGNORECASE)
        # A dictionary of patch series identified by a "series ID".
        # Series ID is an opaque string generated from patch properties
        # (such as message ID, submitter ID, etc.) and representing (not
        # necessarily uniquely) a patch series. Each patch series is a
        # dictionary of XML RPC patch objects identified by the patch's
        # position in the series (extracted from the message subject).
        self.series = dict()

    # TODO Convert this to a simple function
    @property
    def newsince(self):
        return None

    # FIXME Just move this into __init__
    def get_rpc(self, baseurl):
        """
        Create an XML RPC interface for a Patchwork base URL and initialize
        compatibility information.

        Args:
            baseurl:    Patchwork base URL to create the interface with.

        Returns:
            The XML RPC interface for the Patchwork
        """
        rpc = xmlrpclib.ServerProxy("%s/xmlrpc/" % baseurl)
        try:
            ver = rpc.pw_rpc_version()
            # check for normal patchwork1 xmlrpc version numbers
            if not (ver == [1, 3, 0] or ver == 1):
                raise Exception("Unknown xmlrpc version %s", ver)

        except xmlrpclib.Fault as err:
            if err.faultCode == 1 and \
               re.search("index out of range", err.faultString):
                # possible internal RH instance
                rpc = RpcWrapper(rpc)
                ver = rpc.pw_rpc_version()
                if ver < 1010:
                    raise Exception("Unsupported xmlrpc version %s", ver)

                # grab extra info for later parsing
                self.fields = ['id', 'name', 'submitter', 'msgid',
                               ['root_comment', ['headers']],
                               'date', 'project_id']
            else:
                raise Exception("Unknown xmlrpc fault: %s", err.faultString)

        return rpc

    # FIXME Use a verb in the name
    def patchurl(self, patch):
        """
        Format a URL for a patch object.

        Args:
            patch:  Patch object as returned by get_patch_by_id().

        Returns:
            Patch URL.
        """
        return "%s/patch/%d" % (self.baseurl, patch.get("id"))

    def log_patch(self, id, name, message_id, emails):
        """
        Log patch ID, name, Message-ID, and e-mails.

        Args:
            id:         The patch ID to log.
            name:       The patch name to log.
            message_id: The Message-ID header from the patch e-mail.
            emails:     E-mail addresses involved with the patch.
        """
        logging.info("patch %d %s", id, name)
        logging.info("patch %d message_id: %s", id, message_id)
        logging.info("patch %d emails: %s", id, emails)

    def update_patch_name(self, patch):
        """
        Set patch name in a patch XML RPC object from its e-mail Subject, for
        patches coming from internal Red Hat instance, where patch names are
        apparently unsuitable.

        Args:
            patch:  The patch XML RPC object to set the name in.

        Returns:
            The possibly modified patch XML RPC object.
        """
        if 'root_comment' in patch:
            # internal RH only: rewrite the original subject line
            e = email.message_from_string(patch['root_comment']['headers'])
            subject = e.get('Subject')
            if subject is not None:
                subject = subject.replace('\n\t', ' ').replace('\n', ' ')
            # TODO What happens when subject is None?
            patch['name'] = stringify(
                email.header.decode_header(subject)[0][0]
            )

        return patch

    def get_patch_by_id(self, pid):
        """
        Retrieve a patch object by patch ID.

        Args:
            pid:    ID of the patch to retrieve.

        Returns:
            The patch object as returned by XML RPC.
            TODO document at least the fields we care about, Patchwork is not
            likely to document the deprecated XML RPC interface for us.
        """
        if not self.fields:
            patch = self.rpc.patch_get(pid)
        else:
            # internal RH only: special hook to get original subject line
            patch = self.rpc.patch_get(pid, self.fields)

        if patch is None or patch == {}:
            logging.warning("Failed to get data for patch %d", pid)
            patch = None

        self.update_patch_name(patch)

        return patch

    def get_patch_list(self, filt):
        """
        Get a list of patch XML RPC objects, filtered according to the
        specified filter dictionary.

        Args:
            filt:   The filter dictionary structured according to the XML RPC
                    documentation.

        Returns:
            The list of patch XML RPC objects.
        """
        if not self.fields:
            patches = self.rpc.patch_list(filt)
            return patches

        # internal RH only: special hook to get original subject line
        patches = self.rpc.patch_list(filt, False, self.fields)

        # rewrite all subject lines back to original
        for patch in patches:
            self.update_patch_name(patch)

        return patches

    def get_header_value(self, patch_id, *keys):
        """
        Get the value(s) of requested message headers.

        In case multiple headers with the same key are present (this is
        relevant for eg. 'Received' header), concatenating the values with
        double newlines as a divider (we shouldn't need headers which can be
        present multiple times anyways).

        Args:
            patch_id: ID of the patch to retrieve header value for.
            keys:     Keys of the headers which value should be retrieved.

        Returns:
            A tuple of strings representing the value of requested headers
            from patch.
        """
        mbox_string = stringify(self.rpc.patch_get_mbox(patch_id))
        mbox_email = email.message_from_string(mbox_string)

        res = ()

        for key in keys:
            value = mbox_email.get_all(key, [''])
            if len(value) == 1:
                res += (value[0],)
            else:
                res += ('\n\n'.join([val for val in value]),)

        return res

    def get_emails(self, pid):
        """
        Get all involved e-mail addresses from patch message headers.

        Args:
            pid:    ID of the patch to get header values for.

        Returns:
            A set of e-mail addresses involved with the patch.
        """
        emails = set()

        logging.debug("getting emails for patch %d from 'from', 'to', 'cc'")
        header_values = self.get_header_value(pid, "From", "To", "Cc")
        for header_value in header_values:
            for faddr in [x.strip() for x in header_value.split(",") if x]:
                logging.debug("patch=%d; email=%s", pid, faddr)
                maddr = re.search(r"\<([^\>]+)\>", faddr)
                if maddr:
                    emails.add(maddr.group(1))
                else:
                    emails.add(faddr)

        return emails

    def set_patch_check(self, pid, jurl, result):
        """
        Add a patch "check" for the specified patch, with the specified
        Jenkins build URL and result (sktm.tresult).

        Args:
            pid:    The ID of the patch to add the "check" for.
            jurl:   Jenkins build URL for the "check" to reference.
            result: Test result (sktm.tresult) to feature in the "check"
                    state.
        """
        # TODO: Implement this for xmlrpc
        pass

    def dump_patch(self, pid):
        """
        Output the specified patch information to stdout.

        Args:
            pid:    The ID of the patch to dump.
        """
        patch = self.get_patch_by_id(pid)
        print("pinfo=", patch, sep='')
        print("message_id=", self.get_header_value(pid, 'Message-ID'), sep='')
        print("email=", self.get_emails(pid), sep='')

    # TODO Move this to __init__ or make it a class method
    def get_projectid(self, projectname):
        """
        Retrieve ID of the project with the specified name.

        Args:
            projectname:    The name of the project to retrieve ID for.

        Returns:
            The project name.

        Raises:
            A string containing an error message, if the project with the
            specified name was not found.
        """
        plist = self.rpc.project_list(projectname)
        for project in plist:
            if project.get("linkname") == projectname:
                pid = int(project.get("id"))
                logging.debug("%s -> %d", projectname, pid)
                return pid

        raise Exception("Couldn't find project %s" % projectname)

    # FIXME This doesn't just parse a patch. Name/refactor accordingly.
    def parse_patch(self, patch):
        """
        Accumulate an XML RPC patch object into the patch series dictionary,
        skipping patches with names matching skip regex (self.skp), and
        patches with invalid patchset positions. Update the maximum seen patch
        ID (self.lastpatch). Return a summary for the patchset the patch
        belongs to, if the supplied patch completes it (including single-patch
        "patchsets"). Patchset identification is unreliable.

        Args:
            patch   An XML RPC patch object as returned by get_patch_by_id().

        Returns:
            A patchset summary, or none, if patch is skipped or patchset is
            not complete yet.
        """
        pid = patch.get("id")
        pname = patch.get("name")
        result = None

        if self.skp.search(pname):
            logging.info("skipping patch %d: %s", pid, pname)
            if pid > self.lastpatch:
                self.lastpatch = pid
            return result

        # Extract patch position in series and series length from patch name
        smatch = re.search(r"\[.*?(\d+)/(\d+).*?\]", pname)
        # If the patch has series information in its name
        if smatch:
            # Patch position in series
            cpatch = int(smatch.group(1))
            # Number of patches in series
            mpatch = int(smatch.group(2))

            # If patch position is out of range
            if cpatch < 1 or cpatch > mpatch:
                logging.info("skipping patch %d: %s", pid, pname)
                if pid > self.lastpatch:
                    self.lastpatch = pid
                return result

            #
            # Generate series ID
            #
            # FIXME Employ a more reliable algorithm to get project-unique
            #       series IDs. Perhaps identify by submitter ID, and
            #       timestamp clump.

            # Get message ID of the patch e-mail
            mid = patch.get("msgid")

            # Try to extract a part of message ID unique for a series, but
            # common between series e-mails
            mmatch = re.match(r"\<(\d+\W\d+)\W\d+.*@", mid)
            seriesid = None
            if mmatch:
                # Use it if found
                seriesid = mmatch.group(1)
            else:
                # Generate one from submitter ID and number of patches
                # in series, otherwise, which is hardly unique
                seriesid = "%s_%s" % (patch.get("submitter_id"), mpatch)

            #
            # Enter the patch into the series
            #

            # Create series dictionary, if doesn't exist
            if seriesid not in self.series:
                self.series[seriesid] = dict()

            # If the patch number was already seen in this series
            if cpatch in self.series[seriesid]:
                # Skip it
                return result

            # Add it to the series
            self.series[seriesid][cpatch] = patch

            #
            # Output completed series
            #

            # If we already got all the patches in the series
            if len(self.series[seriesid].keys()) == mpatch:
                # Create the patchset summary
                logging.info("---")
                logging.info("patchset: %s", seriesid)

                message_id = None
                subject = None
                all_emails = set()
                patchset = list()
                # For each patch position in series in order
                for cpatch in sorted(self.series[seriesid].keys()):
                    patch = self.series[seriesid].get(cpatch)
                    pid = patch.get("id")
                    message_id, subject = self.get_header_value(pid,
                                                                'Message-ID',
                                                                'Subject')
                    emails = self.get_emails(pid)
                    self.log_patch(pid, patch.get("name"), message_id, emails)
                    all_emails = all_emails.union(emails)
                    patchset.append(self.patchurl(patch))

                logging.info("message_id: %s", message_id)
                logging.info("subject: %s", subject)
                logging.info("emails: %s", all_emails)
                logging.info("---")
                result = PatchsetSummary(message_id,
                                         subject,
                                         all_emails,
                                         patchset)
        # Else, it's a single patch
        else:
            message_id, subject = self.get_header_value(pid,
                                                        'Message-ID',
                                                        'Subject')
            emails = self.get_emails(pid)
            self.log_patch(pid, pname, message_id, emails)
            result = PatchsetSummary(message_id, subject, emails,
                                     [self.patchurl(patch)])

        if pid > self.lastpatch:
            self.lastpatch = pid

        return result

    def get_new_patchsets(self):
        """
        Retrieve a list of summaries for any completed patchsets comprised
        of patches with ID greater than the maximum seen patch ID
        (self.lastpatch). Update the maximum seen patch ID (self.lastpatch).

        Returns:
            A list of patchset summaries.
        """
        patchsets = list()

        logging.debug("get_new_patchsets: %d", self.lastpatch)
        for patch in self.get_patch_list({'project_id': self.projectid,
                                          'id__gt': self.lastpatch}):
            pset = self.parse_patch(patch)
            if pset:
                patchsets.append(pset)
        return patchsets

    # TODO This shouldn't really skip patches to retrieve, should it?
    def get_patchsets(self, patchlist):
        """
        Retrieve a list of summaries of any complete patchsets comprised by a
        list of non-skipped patches with the specified IDs. Update the maximum
        seen patch ID (self.lastpatch).

        Args:
            patchlist:  List of patch IDs to retrieve patchset summaries for,
                        or skip over.

        Returns:
            A list of patchset summaries.
        """
        patchsets = list()

        logging.debug("get_patchsets: %s", patchlist)
        for pid in patchlist:
            patch = self.get_patch_by_id(pid)
            if patch:
                pset = self.parse_patch(patch)
                if pset:
                    patchsets.append(pset)
        return patchsets
