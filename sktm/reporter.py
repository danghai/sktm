# Copyright (c) 2018 Red Hat, Inc. All rights reserved. This copyrighted
# material is made available to anyone wishing to use, modify, copy, or
# redistribute it subject to the terms and conditions of the GNU General
# Public License v.2 or later.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A  PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import os
import re
import smtplib

from sktm.misc import join_with_slash


SUBSTITUTE_RE = re.compile(r'\{[\w\.]+\}')

SUMMARY_PASS = 0
SUMMARY_MERGE_FAILURE = 1
SUMMARY_BUILD_FAILURE = 2
SUMMARY_TEST_FAILURE = 3


class MailAttachment(object):
    def __init__(self, new_name, file_path):
        """
        Create mail attachment.

        Args:
            new_name:  Name to use for the attachment, excluding suffix.
            file_path: Absolute path to the file that should be attached.
        """
        self.filename = new_name
        self.data = self.__mime_data(file_path, file_path.endswith('.gz'))

    def __repr__(self):
        return self.filename

    def __mime_data(self, file_path, compressed):
        """
        Wrap the data from passed file into MIMEText or MIMEApplication
        attachment, based on its type.

        Args:
            file_path:  Absolute path to the file containing the data.
            compressed: True if the data was compressed, False if not.

        Returns:
            Resulting MIMEText or MIMEApplication object containing the data.
        """
        with open(file_path, 'r') as datafile:
            data = datafile.read()

        if compressed:
            attachment = MIMEApplication(data)
        else:
            attachment = MIMEText(data, _charset='utf-8')

        attachment.add_header('content-disposition',
                              'attachment',
                              filename=self.filename)
        return attachment


class MailReporter(object):
    def __init__(self, assets_dir, email_from, email_to, report_intro,
                 report_footer, smtp_url=None, jenkins_job_ids=None,
                 headers=[]):
        """
        Initialize the mail report.

        Args:
            assets_dir:      Directory to retrieve test results from.
            email_to:        List of emails to send the report to.
            email_from:      Sender of the message. If None, defaults to
                             'Kernel-CI kernel-ci@localhost'.
            report_intro:    Path to the file containing text that the report
                             should be prefixed with (report introduction).
            report_footer:   Path to the file containing text that the report
                             should ended with.
            smtp_url:        URL to use as SMTP server, if None localhost is
                             used.
            jenkins_job_ids: List of Jenkins job IDs to add as a custom header.
            headers:         List of headers to add to the report.
        """
        if assets_dir:
            self.assets_dir = os.path.abspath(assets_dir)
        else:
            raise Exception('--assets directory not provided!')

        self.report = MIMEMultipart()
        self.report['From'] = (email_from
                               if email_from
                               else 'Kernel-CI kernel-ci@localhost')
        self.report['To'] = ', '.join([recipient for recipient in email_to])
        for header in headers:
            try:
                key, value = header.split(':', 1)
            except ValueError:  # Add a nice custom error message here
                raise ValueError(
                    'Passed header "%s" not in "key: value" format!' % header
                )
            self.report[key] = value

        self.report_intro = report_intro
        self.report_footer = report_footer

        self.smtp_url = smtp_url if smtp_url else 'localhost'

        # Add Jenkins job IDs to report for debugging purposes
        if jenkins_job_ids:
            self.report['X-JENKINS-IDS'] = ', '.join(jenkins_job_ids)

        # Initialize the list of attachments
        self.attachments = []

    def create_report(self):
        """
        Build the report by merging all info found in the self.assets_dir.
        """
        filename_list = os.listdir(self.assets_dir)

        if 'merge.result' not in filename_list:
            raise Exception('No merge results found in %s! Please check if the'
                            ' provided directory is correct and the testing '
                            'completed without errors.' % self.assets_dir)

        merge_report = join_with_slash(self.assets_dir, 'merge.report')
        result_set_list = []

        if not next((filename for filename in filename_list
                     if filename.startswith(('build', 'run'))), None):
            # Try to grab build / run files from subdirectories
            for filename in filename_list:
                if os.path.isdir(join_with_slash(self.assets_dir, filename)):
                    result_set_list.append(self.__get_results(
                        join_with_slash(self.assets_dir, filename)
                    ))
            result_set_list = [result_set for result_set in result_set_list
                               if result_set]
            if not result_set_list:  # Only merge stage ran
                logging.info('Reporting merge results.')
                self.__create_data(merge_report)
                for attachment in self.attachments:
                    self.report.attach(attachment.data)
                return

            logging.info('Data from multiple runs expected, creating '
                         'multireport.')
            self.__create_data(merge_report, result_set_list)

        else:
            logging.info('Creating single report from %s', self.assets_dir)
            result_set_list.append(self.__get_results(self.assets_dir))
            self.__create_data(merge_report, result_set_list)

        for attachment in self.attachments:
            self.report.attach(attachment.data)

    def __get_results(self, dir_path):
        """
        Retrieve a set of results for a single run from specified directory.

        Args:
            dir_path: Absolute path to the directory result files are supposed
                      to be in.

        Returns:
            A set of absolute file paths of results retrieved from the
            directory.
        """
        results = set([join_with_slash(dir_path, filename)
                       for filename in os.listdir(dir_path)
                       if filename.endswith(('.result', '.report'))])

        logging.debug('Results retrieved from %s: %s', dir_path, results)
        return results

    def __create_data(self, merge_report, result_set_list=[]):
        """
        Format data from logs into a report, attach the body of the report
        (including the template header and footer) and populate
        self.attachments with any attachments specified.

        Args:
            merge_report:    Absolute path to the merge report file.
            result_set_list: List of sets of reports, each set representing one
                             run to report, defaults to [].
        """
        full_report = ''
        test_summary = SUMMARY_PASS

        with open(merge_report, 'r') as merge_file:
            full_report = merge_file.read()

        merge_dir = os.path.dirname(merge_report)
        full_report = self.__substitute_and_attach(full_report, merge_dir)
        with open(join_with_slash(merge_dir, 'merge.result')) as merge_result:
            if merge_result.read().startswith('false'):
                test_summary = SUMMARY_MERGE_FAILURE

        for index, test_run in enumerate(result_set_list):
            test_result_dir = os.path.dirname(next(iter(test_run)))
            build_report = ''
            run_report = ''

            build_result = next((test_result for test_result in test_run
                                 if test_result.endswith('build.result')),
                                None)
            if build_result:
                with open(build_result, 'r') as build_result_file:
                    if build_result_file.read().startswith('false'):
                        test_summary = SUMMARY_BUILD_FAILURE

                build_data = next(test_result for test_result in test_run
                                  if test_result.endswith('build.report'))
                with open(build_data, 'r') as build_report_file:
                    build_report = build_report_file.read()
            build_report = self.__substitute_and_attach(build_report,
                                                        test_result_dir,
                                                        index)

            run_result = next((test_result for test_result in test_run
                               if test_result.endswith('run.result')),
                              None)
            if run_result:
                with open(run_result, 'r') as run_result_file:
                    if (run_result_file.read().startswith('false')
                            and test_summary == SUMMARY_PASS):
                        test_summary = SUMMARY_TEST_FAILURE

                run_data = next(test_result for test_result in test_run
                                if test_result.endswith('run.report'))
                with open(run_data, 'r') as run_report_file:
                    run_report = run_report_file.read()
            run_report = self.__substitute_and_attach(run_report,
                                                      test_result_dir,
                                                      index)

            full_report += '\n' + build_report + run_report

        summary = self.__create_summary(test_summary)

        with open(self.report_intro, 'r') as report_intro_file:
            report_intro_text = report_intro_file.read()
        with open(self.report_footer, 'r') as report_footer_file:
            report_footer_text = report_footer_file.read()

        self.report.attach(MIMEText('\n'.join([report_intro_text,
                                               summary,
                                               full_report,
                                               report_footer_text])))

    def __create_summary(self, status):
        """
        Create a test run summary based on the status.

        Args:
            status: Aggregated status of the runs.

        Returns:
            String representing the overall status of the runs.
        """
        summary = 'Test summary:\n    '

        if status == SUMMARY_PASS:
            summary += 'Testing PASSED'
        elif status == SUMMARY_MERGE_FAILURE:
            summary += 'Merge FAILED'
        elif status == SUMMARY_BUILD_FAILURE:
            summary += 'Build FAILED'
        elif status == SUMMARY_TEST_FAILURE:
            summary += 'Testing FAILED'

        return summary + '\n'

    def __substitute_and_attach(self, text, directory, name_label=None):
        """
        Substitute the placeholders for attachment  filenames in the report
        text and add the references attachments to self.attachments.

        Args:
            text:       Original text of the report.
            directory:  Parent directory of the logs.
            name_label: Label to add to the filename attachment, to be able to
                        differentiate between logs from different runs which
                        have the same name. Defaults to None (eg. for merge
                        reports).

        Returns:
            String reporesenting modified text.
        """
        for to_attach in SUBSTITUTE_RE.findall(text):
            stripped_name = to_attach.strip('}{')
            attachment_path = join_with_slash(directory, stripped_name)
            if name_label:
                try:
                    prefix, suffix = stripped_name.rsplit('.', 1)
                    new_name = '{}_{}.{}'.format(prefix, name_label, suffix)
                except ValueError:
                    new_name = '{}_{}'.format(stripped_name, name_label)
            else:
                new_name = stripped_name

            text = text.replace(to_attach, new_name)
            self.attachments.append(MailAttachment(new_name, attachment_path))

        return text

    def send_report(self):
        """
        Send the email report (self.report), using self.smtp_url as mailserver.
        """
        mailserver = smtplib.SMTP(self.smtp_url)
        mailserver.sendmail(self.report['From'],
                            self.report['To'],
                            self.report.as_string())
        mailserver.quit()
