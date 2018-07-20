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
import email
import email.header
import json
import logging
import re
import urllib
import xmlrpclib

import dateutil.parser
import requests

import sktm.misc


SKIP_PATTERNS = [
    r"\[[^\]]*iproute.*?\]",
    r"\[[^\]]*pktgen.*?\]",
    r"\[[^\]]*ethtool.*?\]",
    r"\[[^\]]*git.*?\]",
    r"\[[^\]]*pull.*?\]",
    r"pull.?request"
]

PW_CHECK_CHOICES = {'pending': 0,
                    'success': 1,
                    'warning': 2,
                    'fail': 3}


class ObjectSummary(object):
    """A summary of an mbox-based Patchwork object"""

    def __init__(self, url, mbox_sfx, date=None, patch_id=None):
        """
        Initialize an object summary.

        Args:
            url:        Patchwork object URL. It should be possible to
                        retrieve the object's mbox by fetching from this URL
                        with a suffix appended.
            date:       The mbox "Date" header value, in the
                        "YYYY-MM-DDTHH:MM:SS" format, where "T" is literal.
            patch_id:   ID of a Patchwork patch, for patch objects.
            mbox_sfx:   The string to add to the object URL to make the object
                        mbox URL.
        """
        # User-facing Patchwork object URL
        self.url = url
        # Mbox URL suffix
        self.mbox_sfx = mbox_sfx
        # "Date" header value
        self.date = date
        # Patchwork patch ID for patch objects
        self.patch_id = patch_id

    def __is_patch(self):
        """
        Check if the object is a patch.

        Returns:
            True if the object is a patch object, False if not.
        """
        return bool(self.patch_id)

    def get_mbox_url(self):
        """
        Get the URL pointing at the object's mbox.

        Returns:
            URL pointing at the object's mbox.
        """
        return sktm.join_with_slash(self.url, self.mbox_sfx)


class SeriesSummary(object):
    """A series summary"""

    def __init__(self):
        """Initialize a series summary"""
        # The "Message-Id" header of the message representing the series
        self.message_id = None
        # The subject of the message representing the series
        self.subject = None
        # A set of e-mail addresses involved with the series
        self.email_addr_set = set()
        # An ObjectSummary of the cover letter, if any
        self.cover_letter = None
        # A list of object summaries (ObjectSummary objects) of patches
        # comprising the series, in the order they should be applied in
        self.patch_list = list()

    def set_message_id(self, message_id):
        """
        Set "Message-Id" header value of the message representing the series.

        Args:
            message_id: The "Message-Id" header value to set.
        """
        self.message_id = message_id

    def set_subject(self, subject):
        """
        Set the subject of the message representing the series.

        Args:
            subject:    The subject to set.
        """
        self.subject = subject

    def set_cover_letter(self, cover_letter):
        """
        Set the cover letter object summary.

        Args:
            cover_letter:   The cover letter object summary to set.
        """
        self.cover_letter = cover_letter

    def merge_email_addr_set(self, email_addr_set):
        """
        Merge a set of e-mail addresses involved with the series into
        the set collected so far.

        Args:
            email_addr_set: The e-mail address set to merge.
        """
        self.email_addr_set |= email_addr_set

    def add_patch(self, patch):
        """
        Add a patch object summary to the list of the patches comprising the
        series.
        """
        self.patch_list.append(patch)

    def is_empty(self):
        """
        Check if a series summary is empty, i.e. doesn't have any patches.

        Returns:
            True if the series summary is empty, False otherwise.
        """
        return not self.patch_list

    def __get_obj_list(self):
        """
        Get a list of summaries of objects representing the series.

        Returns:
            A list of ObjectSummary instances.
        """
        obj_list = list()
        if self.cover_letter:
            obj_list.append(self.cover_letter)
        obj_list += self.patch_list
        return obj_list

    def get_obj_url_list(self):
        """
        Get a list of URLs of objects representing the series.

        Returns:
            A list of mbox-based object URLs.
        """
        return [obj.url for obj in self.__get_obj_list()]

    def get_obj_mbox_url_list(self):
        """
        Get a list of mbox URLs of objects representing the series.

        Returns:
            A list of mbox URLs.
        """
        return [obj.get_mbox_url() for obj in self.__get_obj_list()]

    def get_patch_info_list(self):
        """
        Get a list of patch ID/date tuples for use with database routines.

        Returns:
            A list of tuples, each containing a Patchwork patch ID and the
            value of the "Date" header of the patches comprising the series,
            in the order they should be applied in.
        """
        return [(patch.patch_id, patch.date) for patch in self.patch_list]

    def get_patch_url_list(self):
        """
        Get a list of patch URLs.

        Returns:
            A list of URLs of the patches comprising the series, in the
            order they should be applied in.
        """
        return [patch.url for patch in self.patch_list]

    def get_patch_mbox_url_list(self):
        """
        Get a list of patch mbox URLs.

        Returns:
            A list of URLs pointing to mbox'es of the patches comprising the
            series, in the order they should be applied in.
        """
        return [patch.get_mbox_url() for patch in self.patch_list]

# TODO Move common code to a common parent class


def stringify(value):
    """Convert any value to a str object

    xmlrpc is not consistent: sometimes the same field
    is returned a str, sometimes as unicode. We need to
    handle both cases properly.
    """
    if isinstance(value, unicode):
        return value.encode('utf-8')

    return str(value)


class RpcWrapper(object):
    """
    XMLRPC object wrapper removing magic API version which is added by RH
    Patchwork fork.
    """
    def __init__(self, real_rpc):
        self.rpc = real_rpc
        # RH-Patchwork API version
        self.version = 1010

    def __wrap_call(self, rpc, name):
        """Wrap a RPC call, adding the expected version number as argument."""
        function = getattr(rpc, name)

        def wrapper(*args, **kwargs):
            return function(self.version, *args, **kwargs)
        return wrapper

    def __return_check(self, returned):
        """Returns the real return value without the version info."""
        version = self.version
        if returned[0] != version:
            raise Exception('Patchwork API mismatch (%i, expected %i)' %
                            (returned[0], version))
        return returned[1]

    def __return_unwrapper(self, function):
        def unwrap(*args, **kwargs):
            return self.__return_check(function(*args, **kwargs))
        return unwrap

    def __getattr__(self, name):
        """Add the RPC version checking call/return wrappers."""
        return self.__return_unwrapper(self.__wrap_call(self.rpc, name))


class PatchworkProject(object):
    """Common code for all major versions and interfaces."""
    def __init__(self, baseurl, project_name, skip, is_rh_fork=False):
        """
        Initialize attributes common for all Patchworks.

        Args:
            baseurl:      URL of the Patchwork instance.
            project_name: Project's `linkname` in Patchwork.
            skip:         List of additional regex patterns to skip in patch
                          names, case insensitive.
            is_rh_fork:   True if the instance is internal RH fork, False by
                          default.
        """
        self.baseurl = baseurl
        self.project_id = self._get_project_id(project_name)
        patterns_to_skip = SKIP_PATTERNS + skip
        logging.debug('Patch subject patterns to skip: %s', patterns_to_skip)
        self.skip = re.compile('|'.join(patterns_to_skip), re.IGNORECASE)
        self.is_rh_fork = is_rh_fork

    def __get_patch_message(self, patch_id):
        """
        Retrieve patch's mbox as email object.

        Args:
            patch_id: The ID of the patch which mbox should be retrieved.

        Returns:
            Email object created from the mbox file.

        Raises:
            requests.exceptions.RequestException (and subexceptions) in case
            of requests exceptions, Exception in case of unexpected return code
            (eg. nonexistent patch).
        """
        mbox_url = sktm.join_with_slash(self.baseurl,
                                        'patch',
                                        str(patch_id),
                                        self._get_mbox_url_sfx())

        try:
            response = requests.get(mbox_url)
        except requests.exceptions.RequestException as exc:
            raise exc

        if response.status_code != requests.codes.ok:
            raise Exception('Failed to retrieve patch from %s, returned %d' %
                            (mbox_url, response.status_code))

        return email.message_from_string(response.content)

    def _get_header_values_all(self, patch_id, *name_tuple):
        """
        Get all values (or empty strings) for specified headers from a patch
        message.

        Args:
            patch_id:   ID of the patch to retrieve header values for.
            name_tuple: An n-tuple of names of the headers which values should
                        be retrieved.

        Returns:
            An n-tuple of string lists, representing all the values of the
            specified headers from the patch message, with a list of a single
            empty string for each missing header.
        """
        mbox_email = self.__get_patch_message(patch_id)

        value_list_tuple = ()
        for name in name_tuple:
            # Get and unfold header values
            value_list = [re.sub(r'\r?\n[ \t]', ' ', value)
                          for value in mbox_email.get_all(name, [''])]
            value_list_tuple += (value_list,)
        return value_list_tuple

    def _get_header_values_first(self, patch_id, *name_tuple):
        """
        Get first values (or empty strings) of specified headers from a patch
        message.

        Args:
            patch_id:   ID of the patch to retrieve header values for.
            name_tuple: An n-tuple of names of the headers which first values
                        should be retrieved.

        Returns:
            An n-tuple of strings, representing the first values of the
            specified headers from the patch message, with empty strings
            returned for missing headers.
        """
        return (value_list[0] for value_list in
                self._get_header_values_all(patch_id, *name_tuple))

    def _get_emails(self, pid):
        """
        Get all involved e-mail addresses from patch message headers.

        Args:
            pid:    ID of the patch to get e-mail addresses for.

        Returns:
            A set of e-mail addresses involved with the patch.
        """
        email_set = set()
        logging.debug("getting emails for patch %d from 'from', 'to', 'cc'",
                      pid)
        for header_value_list in \
                self._get_header_values_all(pid, "From", "To", "Cc"):
            email_set |= set(addr_tuple[1]
                             for addr_tuple
                             in email.utils.getaddresses(header_value_list)
                             if addr_tuple[1])
        logging.debug("patch=%d; email_set=%s", pid, email_set)

        return email_set

    def _get_patch_url(self, patch):
        """
        Build a Patchwork URL for passed patch object.

        Args:
            patch: Patch object, either Patchwork2's JSON object or
                   Patchwork1's XMLRPC object.

        Returns:
            Patch URL.
        """
        return sktm.join_with_slash(self.baseurl,
                                    'patch',
                                    str(patch.get('id')))

    def _get_mbox_url_sfx(self):
        """
        Retrieve the string which needs to be added to a patch URL to make an
        mbox URL.

        Returns:
            The patch mbox URL suffix.
        """
        if self.is_rh_fork:
            return "mbox4"

        return "mbox"


class PatchworkV2Project(PatchworkProject):
    """
    A Patchwork REST interface
    """
    def __init__(self, baseurl, projectname, since, apikey=None, skip=[]):
        """
        Initialize a Patchwork REST interface.

        Args:
            baseurl:        Patchwork base URL.
            projectname:    Patchwork project name, or None.
            since:          Last processed patch timestamp in a format
                            accepted by dateutil.parser.parse. Patches with
                            this or earlier timestamp will be ignored.
            apikey:         Patchwork API authentication token.
            skip:           List of additional regex patterns to skip in patch
                            names, case insensitive.
        """
        # Last processed patch timestamp in a dateutil.parser.parse format
        self.since = since
        # TODO Describe
        self.nsince = None
        # Patchwork API authentication token.
        self.apikey = apikey
        # JSON representation of API URLs retrieved from the Patchwork server
        self.apiurls = self.__get_apiurls(baseurl)
        super(PatchworkV2Project, self).__init__(baseurl, projectname, skip)

    def _get_project_id(self, project_name):
        """
        Retrieve project ID based on project's name.

        Args:
            project_name:  The name of the project to retrieve.

        Returns:
            Integer representing project's ID.
        """
        response = requests.get(
            sktm.join_with_slash(self.apiurls.get("projects"),
                                 project_name)
        )
        if response.status_code != requests.codes.ok:
            raise Exception("Can't get project data: %s %d" %
                            (project_name, response.status_code))
        return response.json().get('id')

    def __get_apiurls(self, baseurl):
        """
        Retrieve JSON representation of the list of API URLs supported by the
        Patchwork server.

        Returns:
            The JSON representation of the API URLs.
        """
        response = requests.get(sktm.join_with_slash(baseurl, "api"))
        if response.status_code != 200:
            raise Exception("Can't get apiurls: %d" % response.status_code)

        return response.json()

    def __get_series_from_url(self, url):
        """
        Retrieve a list of applicable series summaries for the specified
        series URL. Series or patches matching skip patterns (self.skip) are
        excluded.

        Args:
            url:    The patch series, or patch series list URL to retrieve
                    series summaries for.

        Returns:
            A list of SeriesSummary objects.
        """
        series_list = list()

        logging.debug("get_series_from_url %s", url)
        response = requests.get(url)

        if response.status_code != 200:
            raise Exception("Can't get series from url %s (%d)" %
                            (url, response.status_code))

        sdata = response.json()
        # If there is a single series returned we get a dict, not a list with
        # a single element. Fix this inconsistency for easier processing.
        if not isinstance(sdata, list):
            sdata = [sdata]

        for series in sdata:
            series_summary = SeriesSummary()

            if not series.get("received_all"):
                logging.info("skipping incomplete series: [%d] %s",
                             series.get("id"), series.get("name"))
                continue

            if self.skip.search(series.get("name")):
                logging.info("skipping series %d: %s", series.get("id"),
                             series.get("name"))
                continue

            cover = series.get("cover_letter")
            if cover:
                match = re.match("^(.*)/mbox/?$", cover.get("mbox", ""))
                if match:
                    series_summary.set_cover_letter(
                        ObjectSummary(match.group(1),
                                      self._get_mbox_url_sfx(),
                                      cover.get("date"))
                    )

            logging.info("series [%d] %s", series.get("id"),
                         series.get("name"))

            for patch in series.get("patches"):
                logging.info("patch [%d] %s", patch.get("id"),
                             patch.get("name"))

                if self.skip.search(patch.get("name")):
                    logging.info("skipping patch %d: %s",
                                 patch.get("id"),
                                 patch.get("name"))
                    continue

                message_id, subject = \
                    self._get_header_values_first(patch.get("id"),
                                                  'Message-ID',
                                                  'Subject')
                emails = self._get_emails(patch.get("id"))
                logging.debug("patch [%d] message_id: %s", patch.get("id"),
                              message_id)
                logging.debug("patch [%d] subject: %s", patch.get("id"),
                              subject)
                logging.debug("patch [%d] emails: %s", patch.get("id"),
                              emails)
                series_summary.set_message_id(message_id)
                series_summary.set_subject(subject)
                series_summary.merge_email_addr_set(emails)
                series_summary.add_patch(
                    ObjectSummary(self._get_patch_url(patch),
                                  self._get_mbox_url_sfx(),
                                  patch.get("date"),
                                  patch.get("id"))
                )
            logging.info("---")

            if not series_summary.is_empty():
                logging.debug("series [%d] message_id: %s", series.get("id"),
                              series_summary.message_id)
                logging.debug("series [%d] subject: %s", series.get("id"),
                              series_summary.subject)
                logging.debug("series [%d] emails: %s", series.get("id"),
                              series_summary.email_addr_set)
                series_list.append(series_summary)

        link = response.headers.get("Link")
        if link is not None:
            m = re.match("<(.*)>; rel=\"next\"", link)
            if m:
                nurl = m.group(1)
                # TODO Limit recursion
                series_list += self.__get_series_from_url(nurl)

        return series_list

    def __get_patchsets_from_events(self, url):
        """
        Retrieve a list of applicable series summaries for the specified
        event list URL. Series and patches which names match one of skip
        patterns (self.skip) are excluded.

        Args:
            url:    The event list URL to retrieve series summaries for.

        Returns:
            A list of SeriesSummary objects.
        """
        series_list = list()

        logging.debug("get_patchsets_from_events: %s", url)
        response = requests.get(url)

        if response.status_code != 200:
            raise Exception("Can't get events from url %s (%d)" %
                            (url, response.status_code))

        edata = response.json()
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

            series_list += self.__get_series_from_url(series.get("url"))

        link = response.headers.get("Link")
        if link is not None:
            m = re.match("<(.*)>; rel=\"next\"", link)
            if m:
                nurl = m.group(1)
                # TODO Limit recursion
                series_list += self.__get_patchsets_from_events(nurl)

        return series_list

    def __set_patch_check(self, patch, payload):
        """
        Add a patch "check" payload for the specified JSON representation of a
        patch.

        Args:
            patch:      JSON representation of a patch to add the check for.
            payload:    The "check" payload dictionary to be converted to JSON.
        """
        response = requests.post(
            patch.get("checks"),
            headers={"Authorization": "Token %s" % self.apikey,
                     "Content-Type": "application/json"},
            data=json.dumps(payload)
        )

        if response.status_code not in [200, 201]:
            logging.warning("Failed to post patch check: %d",
                            response.status_code)

    def set_patch_check(self, pid, jurl, result):
        """
        Add a patch "check" for the specified patch, with the specified
        Jenkins build URL and result (sktm.misc.TestResult). The result
        cannot be sktm.misc.TestResult.ERROR.

        Args:
            pid:    The ID of the patch to add the "check" for.
            jurl:   Jenkins build URL for the "check" to reference.
            result: Test result (sktm.misc.TestResult) to feature
                    in the "check" state.
        """
        if self.apikey is None:
            logging.debug("No patchwork api key provided, not setting checks")
            return

        payload = {'patch': pid,
                   'state': None,
                   'target_url': jurl,
                   'context': 'Kernel CI',
                   'description': 'Kernel CI testing'}
        if result == sktm.misc.TestResult.SUCCESS:
            payload['state'] = PW_CHECK_CHOICES['success']
        else:
            payload['state'] = PW_CHECK_CHOICES['fail']
            payload['description'] = str(result)

        self.__set_patch_check(self.get_patch_by_id(pid), payload)

    def get_patch_by_id(self, pid):
        """
        Retrieve a patch object by patch ID.

        Args:
            pid:    ID of the patch to retrieve.

        Returns:
            Parsed JSON object representing the patch and its attributes. The
            set of supported attributes depends on which API versions are
            supported by a specific Patchwork instance.
        """
        response = requests.get(
            sktm.join_with_slash(self.apiurls.get("patches"),
                                 str(pid))
        )

        if response.status_code != 200:
            raise Exception("Can't get patch by id %d (%d)" %
                            (pid, response.status_code))

        return response.json()

    def __get_patchsets_by_patch(self, url, seen=set()):
        """
        Retrieve a list of series summaries, which weren't already "seen", and
        which contain the patch or patches available at the specified URL.

        Args:
            url:    The URL pointing to a patch or a patch list to retrieve
                    the list of patch series from.
            seen:   A set of IDs of patch series which should be ignored, and
                    which should have patch series IDs added once they're
                    processed.

        Returns:
            A list of SeriesSummary objects.
        """
        series_list = list()

        logging.debug("get_patchsets_by_patch %s", url)
        response = requests.get(url)

        if response.status_code != 200:
            raise Exception("Can't get series from url %s (%d)" %
                            (url, response.status_code))

        pdata = response.json()
        # If there is a single patch returned we get a dict, not a list with
        # a single element. Fix this inconsistency for easier processing.
        if type(pdata) is not list:
            pdata = [pdata]

        for patch in pdata:
            # For each patch series the patch belongs to
            for series in patch.get("series"):
                sid = series.get("id")
                if sid in seen:
                    continue
                else:
                    series_list += self.__get_series_from_url(
                        sktm.join_with_slash(self.apiurls.get("series"),
                                             str(sid))
                    )
                    seen.add(sid)

        link = response.headers.get("Link")
        if link:
            m = re.match("<(.*)>; rel=\"next\"", link)
            if m:
                nurl = m.group(1)
                # TODO Limit recursion
                series_list += self.__get_patchsets_by_patch(nurl, seen)

        return series_list

    def get_new_patchsets(self):
        """
        Retrieve a list of series summaries. Series and patches which names
        match one of skip patterns (self.skip) are excluded.

        Returns:
            A list series summaries.
        """
        # Timestamp filtering for 'since' parameter uses '>=' operation so by
        # using unmodified time, we'd get the last series from previous run
        # again. Add a second to it in order to avoid re-running tests for this
        # last seen series.
        nsince = dateutil.parser.parse(
            self.since
        ) + datetime.timedelta(seconds=1)

        logging.debug("get_new_patchsets since %s", nsince.isoformat())
        new_series = self.__get_patchsets_by_patch(
            "%s?project=%d&since=%s" % (self.apiurls.get("patches"),
                                        self.project_id,
                                        urllib.quote(
                                            nsince.isoformat()
                                        )))
        return new_series

    def get_patchsets(self, patchlist):
        """
        Retrieve a list of applicable series summaries for the specified
        list of patch IDs. Patches which names match one of skip patterns
        (self.skip) are excluded from the series.

        Args:
            patchlist:  List of patch IDs to retrieve series summaries for,
                        or skip over.

        Returns:
            A list of SeriesSummary objects.
        """
        series_list = list()
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
                        series_list += self.__get_series_from_url(
                            sktm.join_with_slash(self.apiurls.get("series"),
                                                 str(sid))
                        )
                        seen.add(sid)

        return series_list


class PatchworkV1Project(PatchworkProject):
    """
    A Patchwork XML RPC interface
    """
    def __init__(self, baseurl, projectname, lastpatch, skip=[]):
        """
        Initialize a Patchwork XML RPC interface.

        Args:
            baseurl:        Patchwork base URL.
            projectname:    Patchwork project name, or None.
            lastpatch:      Maximum processed patch ID to start with.
            skip:           List of additional regex patterns to skip in patch
                            names, case insensitive.
        """
        # A list of patch object fields to request from RH fork of Patchwork
        # Only set if it's a RH fork.
        self.fields = None
        # XML RPC interface to Patchwork
        self.rpc = self.__get_rpc(baseurl)
        # Maximum processed patch ID
        self.lastpatch = lastpatch
        # A dictionary of patch series identified by a "series ID".
        # Series ID is an opaque string generated from patch properties
        # (such as message ID, submitter ID, etc.) and representing (not
        # necessarily uniquely) a patch series. Each patch series is a
        # dictionary of XML RPC patch objects identified by the patch's
        # position in the series (extracted from the message subject).
        self.series = dict()
        # A dictionary of series cover letter patch objects identified by
        # "series IDs", the same ones used in "series' above.
        self.covers = dict()
        super(PatchworkV1Project, self).__init__(
            baseurl,
            projectname,
            skip,
            is_rh_fork=True if self.fields else False
        )

    # FIXME Just move this into __init__
    def __get_rpc(self, baseurl):
        """
        Create an XML RPC interface for a Patchwork base URL and initialize
        compatibility information.

        Args:
            baseurl:    Patchwork base URL to create the interface with.

        Returns:
            The XML RPC interface for the Patchwork
        """
        rpc = xmlrpclib.ServerProxy(sktm.join_with_slash(baseurl, "xmlrpc/"))
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

    def __log_patch(self, id, name, message_id, emails):
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

    def __update_patch_name(self, patch):
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
            msg = email.message_from_string(patch['root_comment']['headers'])
            subject = msg.get('Subject')
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
        if not self.is_rh_fork:
            patch = self.rpc.patch_get(pid)
        else:
            # internal RH only: special hook to get original subject line
            patch = self.rpc.patch_get(pid, self.fields)

        if patch is None or patch == {}:
            logging.warning("Failed to get data for patch %d", pid)
            patch = None

        self.__update_patch_name(patch)

        return patch

    def __get_patch_list(self, filt):
        """
        Get a list of patch XML RPC objects, filtered according to the
        specified filter dictionary.

        Args:
            filt:   The filter dictionary structured according to the XML RPC
                    documentation.

        Returns:
            The list of patch XML RPC objects.
        """
        if not self.is_rh_fork:
            patches = self.rpc.patch_list(filt)
            return patches

        # internal RH only: special hook to get original subject line
        patches = self.rpc.patch_list(filt, False, self.fields)

        # rewrite all subject lines back to original
        for patch in patches:
            self.__update_patch_name(patch)

        return patches

    def set_patch_check(self, pid, jurl, result):
        """
        Add a patch "check" for the specified patch, with the specified
        Jenkins build URL and result (sktm.misc.TestResult). The result
        cannot be sktm.misc.TestResult.ERROR.

        Args:
            pid:    The ID of the patch to add the "check" for.
            jurl:   Jenkins build URL for the "check" to reference.
            result: Test result (sktm.misc.TestResult) to feature
                    in the "check" state.
        """
        # TODO: Implement this for xmlrpc
        pass

    # TODO Move this to __init__ or make it a class method
    def _get_project_id(self, projectname):
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
    def __parse_patch(self, patch):
        """
        Accumulate an XML RPC patch object into the patch series dictionary,
        skipping patches with names matching skip regex (self.skip), and
        patches with invalid patchset positions. Update the maximum seen patch
        ID (self.lastpatch). Return a summary for the patchset the patch
        belongs to, if the supplied patch completes it (including single-patch
        "patchsets"). Patchset identification is unreliable.

        Args:
            patch   An XML RPC patch object as returned by get_patch_by_id().

        Returns:
            A series summary, or none, if patch is skipped or seires are
            not complete yet.
        """
        pid = patch.get("id")
        pname = patch.get("name")
        result = None

        if self.skip.search(pname):
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

            # If it's a cover letter
            if cpatch == 0:
                # Remember the cover letter object
                self.covers[seriesid] = patch
            # Else, if it's a patch
            elif cpatch >= 1 and cpatch <= mpatch:
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
                    # Create the series summary
                    logging.info("---")
                    logging.info("patchset: %s", seriesid)

                    result = SeriesSummary()
                    cover = self.covers.get(seriesid)
                    if cover:
                        result.set_cover_letter(
                            ObjectSummary(self._get_patch_url(cover),
                                          self._get_mbox_url_sfx(),
                                          cover.get("date").replace(" ", "T"),
                                          cover.get("id"))
                        )

                    # For each patch position in series in order
                    for cpatch in sorted(self.series[seriesid].keys()):
                        patch = self.series[seriesid].get(cpatch)
                        pid = patch.get("id")
                        message_id, subject = \
                            self._get_header_values_first(pid,
                                                          'Message-ID',
                                                          'Subject')
                        emails = self._get_emails(pid)
                        self.__log_patch(pid, patch.get("name"),
                                         message_id, emails)
                        result.set_message_id(message_id)
                        result.set_subject(subject)
                        result.merge_email_addr_set(emails)
                        result.add_patch(
                            ObjectSummary(self._get_patch_url(patch),
                                          self._get_mbox_url_sfx(),
                                          patch.get("date").replace(" ", "T"),
                                          pid)
                        )

                    logging.info("message_id: %s", result.message_id)
                    logging.info("subject: %s", result.subject)
                    logging.info("emails: %s", result.email_addr_set)
                    logging.info("---")
            # Otherwise the patch message position is out of range
            else:
                logging.info("skipping patch %d: %s", pid, pname)
                if pid > self.lastpatch:
                    self.lastpatch = pid
                return result
        # Else, it's a single patch
        else:
            message_id, subject = self._get_header_values_first(pid,
                                                                'Message-ID',
                                                                'Subject')
            emails = self._get_emails(pid)
            self.__log_patch(pid, pname, message_id, emails)
            result = SeriesSummary()
            result.set_message_id(message_id)
            result.set_subject(subject)
            result.merge_email_addr_set(emails)
            result.add_patch(
                ObjectSummary(self._get_patch_url(patch),
                              self._get_mbox_url_sfx(),
                              patch.get("date").replace(" ", "T"),
                              pid)
            )

        if pid > self.lastpatch:
            self.lastpatch = pid

        return result

    def get_new_patchsets(self):
        """
        Retrieve a list of summaries for any completed series comprised
        of patches with ID greater than the maximum seen patch ID
        (self.lastpatch). Update the maximum seen patch ID (self.lastpatch).

        Returns:
            A list of SeriesSummary objects.
        """
        series_list = list()

        logging.debug("get_new_patchsets: %d", self.lastpatch)
        for patch in self.__get_patch_list({'project_id': self.project_id,
                                            'id__gt': self.lastpatch}):
            pset = self.__parse_patch(patch)
            if pset:
                series_list.append(pset)
        return series_list

    # TODO This shouldn't really skip patches to retrieve, should it?
    def get_patchsets(self, patchlist):
        """
        Retrieve a list of summaries of any complete series comprised by a
        list of non-skipped patches with the specified IDs. Update the maximum
        seen patch ID (self.lastpatch).

        Args:
            patchlist:  List of patch IDs to retrieve series summaries for,
                        or skip over.

        Returns:
            A list of SeriesSummary objects.
        """
        series_list = list()

        logging.debug("get_patchsets: %s", patchlist)
        for pid in patchlist:
            patch = self.get_patch_by_id(pid)
            if patch:
                pset = self.__parse_patch(patch)
                if pset:
                    series_list.append(pset)
        return series_list
