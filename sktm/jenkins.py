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

import json
import logging
import time

import jenkinsapi

import sktm


class skt_jenkins(object):
    """Jenkins interface"""
    def __init__(self, url, username=None, password=None):
        """
        Initialize a Jenkins interface.

        Args:
            url:         Jenkins instance URL.
            username:    Jenkins user name.
            password:    Jenkins user password.
        """
        # TODO Add support for CSRF protection
        self.server = jenkinsapi.jenkins.Jenkins(url, username, password)

    def _wait_and_get_build(self, jobname, buildid):
        job = self.server.get_job(jobname)
        build = job.get_build(buildid)
        build.block_until_complete(delay=60)

        # call get_build again to ensure we have the results
        build = job.get_build(buildid)

        return build

    def __get_data_list(self, jobname, buildid, stepname, key):
        """
        Get a list of values of a build resultset key, for all steps matching
        the specified name, of the specified completed build, for the
        specified project. Wait for the build to complete, if it hasn't yet.

        Args:
            jobname:    Jenkins project name.
            buildid:    Jenkins build ID.
            stepname:   A path matching test steps in the result, which
                        resultset should be accessed.
            key:        Name of the resultset key to retrieve value of.

        Returns:
            The list of key values.
        """
        value_list = []
        build = self._wait_and_get_build(jobname, buildid)

        if not build.has_resultset():
            raise Exception("No results for build %d (%s)" %
                            (buildid, build.get_status()))

        for (result_key, value) in build.get_resultset().iteritems():
            if result_key == stepname:
                value_list.append(value.__dict__[key])

        return value_list

    def __get_cfg_data_list(self, jobname, buildid, stepname,
                            cfgkey, default=None):
        """
        Get a list of values from a JSON-formatted output of a test result,
        for all steps matching the specified name, of the specified completed
        build for the specified project. Wait for the build to complete, if it
        hasn't yet.

        Args:
            jobname:    Jenkins project name.
            buildid:    Jenkins build ID.
            stepname:   A path matching test steps in the result, which output
                        should be parsed as JSON.
            cfgkey:     Name of the JSON key to retrieve value of.
            default:    The default value to use if a key is not found, for
                        each matching step. Optional, assumed None, if not
                        specified.

        Returns:
            The list of key values, with defaults for steps where they were
            not found.
        """
        value_list = []
        for stdout in self.__get_data_list(jobname, buildid,
                                           stepname, "stdout"):
            logging.debug("stdout=%s", stdout)
            cfg = json.loads(stdout)
            value_list.append(cfg.get(cfgkey, default))

        return value_list

    def __get_cfg_data_uniform(self, jobname, buildid, stepname,
                               cfgkey, default=None):
        """
        Get a uniform value from a JSON-formatted output of a test result,
        for all steps matching the specified name, of the specified completed
        build for the specified project. Wait for the build to complete, if it
        hasn't yet. Throw an exception if the value is not uniform across all
        steps.

        Args:
            jobname:    Jenkins project name.
            buildid:    Jenkins build ID.
            stepname:   A path matching test steps in the result, which output
                        should be parsed as JSON.
            cfgkey:     Name of the JSON key to retrieve value of.
            default:    The default value to use if a key is not found, for
                        each matching step. Optional, assumed None, if not
                        specified.

        Returns:
            The value uniform for the key across all steps.
        """
        def verify(x, y):
            if x != y:
                raise Exception("Non-uniform value of key %s: %s != %s",
                                cfgkey, x, y)
            return x

        return reduce(verify,
                      self.__get_cfg_data_list(jobname, buildid, stepname,
                                               cfgkey, default))

    def __get_cfg_data_max(self, jobname, buildid, stepname,
                           cfgkey, default=None):
        """
        Get the maximum value from a JSON-formatted output of a test result,
        for all steps matching the specified name, of the specified completed
        build for the specified project. Wait for the build to complete, if it
        hasn't yet.

        Args:
            jobname:    Jenkins project name.
            buildid:    Jenkins build ID.
            stepname:   A path matching test steps in the result, which output
                        should be parsed as JSON.
            cfgkey:     Name of the JSON key to retrieve value of.
            default:    The default value to use if a key is not found, for
                        each matching step. Optional, assumed None, if not
                        specified.

        Returns:
            The maximum value of the key across all steps.
        """
        return reduce(lambda x, y: (x if x > y else y),
                      self.__get_cfg_data_list(jobname, buildid, stepname,
                                               cfgkey, default))

    def get_base_commitdate(self, jobname, buildid):
        """
        Get base commit's committer date of the specified completed build for
        the specified project. Wait for the build to complete, if it hasn't
        yet.

        Args:
            jobname:    Jenkins project name.
            buildid:    Jenkins build ID.

        Return:
            The epoch timestamp string of the committer date.
        """
        return self.__get_cfg_data_uniform(jobname, buildid, "skt.cmd_merge",
                                           "commitdate")

    def get_base_hash(self, jobname, buildid):
        """
        Get base commit's hash of the specified completed build for the
        specified project. Wait for the build to complete, if it hasn't yet.

        Args:
            jobname:    Jenkins project name.
            buildid:    Jenkins build ID.

        Return:
            The base commit's hash string.
        """
        return self.__get_cfg_data_uniform(jobname, buildid, "skt.cmd_merge",
                                           "basehead")

    # FIXME Clarify function name
    def get_patchwork(self, jobname, buildid):
        """
        Get the list of Patchwork patch URLs for the specified completed build
        for the specified project. Wait for the build to complete, if it
        hasn't yet.

        Args:
            jobname:    Jenkins project name.
            buildid:    Jenkins build ID.

        Return:
            The list of Patchwork patch URLs.
        """
        return self.__get_cfg_data_uniform(jobname, buildid, "skt.cmd_merge",
                                           "pw")

    def get_baseretcode(self, jobname, buildid):
        """
        Get the maximum (the worst) return code of a baseline test across all
        "run" steps for the specified completed build of the specified
        project. Wait for the build to complete, if it hasn't yet.
        """
        return self.__get_cfg_data_max(jobname, buildid, "skt.cmd_run",
                                       "baseretcode", 0)

    def get_result_url(self, jobname, buildid):
        return "%s/job/%s/%s" % (self.server.base_server_url(), jobname,
                                 buildid)

    def get_result(self, jobname, buildid):
        """
        Get the status of a build for specified project name and build ID.

        Args:
            jobname:    Jenkins project name.
            buildid:    Jenkins build ID.

        Return:
            Status of the build (an sktm.tresult).
        """
        build = self._wait_and_get_build(jobname, buildid)

        bstatus = build.get_status()
        logging.info("build_status=%s", bstatus)

        if bstatus == "SUCCESS":
            return sktm.tresult.SUCCESS

        # If build is UNSTABLE and all cmd_run steps are PASSED or FIXED
        if bstatus == "UNSTABLE" and \
                (set(self.__get_data_list(jobname, buildid,
                                          "skt.cmd_run", "status")) <=
                 set(["PASSED", "FIXED"])):
            # If there was at least one baseline test failure
            if self.get_baseretcode(jobname, buildid) != 0:
                logging.warning("baseline failure found during patch testing")
                return sktm.tresult.BASELINE_FAILURE

            return sktm.tresult.SUCCESS

        # Find earliest (worst) step failure
        step_failure_result_list = [
            ("skt.cmd_merge", sktm.tresult.MERGE_FAILURE),
            ("skt.cmd_build", sktm.tresult.BUILD_FAILURE),
            ("skt.cmd_run", sktm.tresult.TEST_FAILURE),
        ]
        for (step, failure_result) in step_failure_result_list:
            if set(self.__get_data_list(jobname, buildid, step, "status")) & \
                    set(["FAILED", "REGRESSION"]):
                return failure_result

        logging.warning("Unknown status. marking as test failure")
        return sktm.tresult.TEST_FAILURE

    # FIXME Clarify/fix argument names
    def build(self, jobname, baserepo=None, ref=None, baseconfig=None,
              message_id=None, subject=None, emails=set(), patchwork=[],
              makeopts=None):
        """
        Submit a build of a patch series.

        Args:
            jobname:    Name of the Jenkins project to build.
            baserepo:   Baseline Git repo URL.
            ref:        Baseline Git reference to test.
            baseconfig: Kernel configuration URL.
            message_id: Value of the "Message-Id" header of the e-mail
                        message representing the series, or None if unknown.
            subject:    Subject of the message representing the series, or
                        None if unknown.
            emails:     Set of e-mail addresses involved with the series to
                        send notifications to.
            patchwork:  List of URLs pointing to patches to apply.
            makeopts:   String of extra arguments to pass to the build's make
                        invocation.

        Returns:
            Submitted build number.
        """
        params = dict()
        if baserepo is not None:
            params["baserepo"] = baserepo

        if ref is not None:
            params["ref"] = ref

        if baseconfig is not None:
            params["baseconfig"] = baseconfig

        if message_id:
            params["message_id"] = message_id

        if subject:
            params["subject"] = subject

        if emails:
            params["emails"] = ",".join(emails)

        if patchwork:
            params["patchwork"] = " ".join(patchwork)

        if makeopts is not None:
            params["makeopts"] = makeopts

        logging.debug(params)
        self.server.get_job(jobname)
        expected_id = self.server.get_job(jobname).get_next_build_number()
        self.server.build_job(jobname, params)
        build = self.find_build(jobname, params, expected_id)
        logging.info("submitted build: %s", build)
        return build.get_number()

    def is_build_complete(self, jobname, buildid):
        job = self.server.get_job(jobname)
        build = job.get_build(buildid)

        return not build.is_running()

    def _params_eq(self, build, params):
        try:
            build_params = build.get_actions()["parameters"]
        except (AttributeError, KeyError):
            return False

        for build_param in build_params:
            if (build_param["name"] in params
                    and build_param["value"] != params[build_param["name"]]):
                return False

        return True

    def find_build(self, jobname, params, eid=None):
        job = self.server.get_job(jobname)
        lbuild = None

        while not lbuild:
            try:
                lbuild = job.get_last_build()
            except jenkinsapi.custom_exceptions.NoBuildData:
                time.sleep(1)

        if eid is not None:
            while lbuild.get_number() < eid:
                time.sleep(1)
                lbuild = job.get_last_build()
        if self._params_eq(lbuild, params):
            return lbuild

        # slowpath
        for bid in job.get_build_ids():
            build = job.get_build(bid)
            if self._params_eq(build, params):
                return build
        return None
