# Copyright (c) 2017-2018 Red Hat, Inc. All rights reserved. This copyrighted
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

import argparse
import ConfigParser
import logging
import os
import sktm.reporter
import sktm
import sktm.jenkins


DEFAULT_REPORT_INTRO = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    '../templates/report.header'
)
DEFAULT_REPORT_FOOTER = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    '../templates/report.footer'
)

DEFAULT_JENKINS_RETRY_COUNT = 30


def setup_parser():
    """
    Create an sktm command line parser.

    Returns:
        The created parser.
    """
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-v",
        "--verbose",
        help="Increase verbosity level",
        action="count",
        default=0
    )
    parser.add_argument(
        "--rc",
        help="Path to rc file",
        default="~/.sktmrc"
    )
    parser.add_argument(
        "--db",
        help="Path to db file",
        default="~/.sktm.db"
    )
    parser.add_argument(
        "--jurl",
        help="Jenkins URL"
    )
    parser.add_argument(
        "--jlogin",
        help="Jenkins login"
    )
    parser.add_argument(
        "--jpass",
        help="Jenkins password"
    )
    parser.add_argument(
        "--jretry",
        type=int,
        help="Counter to retry Jenkins, default to %d" %
        DEFAULT_JENKINS_RETRY_COUNT
    )
    parser.add_argument(
        "--jjname",
        help="Jenkins job name"
    )
    parser.add_argument(
        "--makeopts",
        help="Specify options for make"
    )
    parser.add_argument(
        "--cfgurl",
        type=str,
        help="Kernel config URL"
    )

    # Reporting-related arguments
    parser.add_argument(
        '--mail-to',
        action='append',
        default=[],
        type=str,
        help='Email address to send the report to (on top of recipients '
        'grabbed from original patch headers, if applicable). Can be specified'
        ' more times'
    )
    parser.add_argument(
        '--mail-from',
        type=str,
        help='Report\'s sender, as will appear on the "From" line'
    )
    parser.add_argument(
        '--report-intro',
        type=str,
        help='Path to file containing the report introduction, defaults to '
        'templates/report.header'
    )
    parser.add_argument(
        '--report-footer',
        type=str,
        help='Path to file containing the report introduction, defaults to '
        'templates/report.header'
    )
    parser.add_argument(
        '--mail-header',
        action='append',
        default=[],
        type=str,
        help='Header to add to the report in format "Key: Value". Can be '
        'specified more times'
    )
    parser.add_argument('--smtp-url',
                        type=str,
                        help='Use SMTP URL instead of localhost to send mail')

    subparsers = parser.add_subparsers()

    parser_baseline = subparsers.add_parser("baseline")
    parser_baseline.add_argument(
        "repo",
        type=str,
        help="Base repo URL"
    )
    parser_baseline.add_argument(
        "ref",
        type=str,
        help="Base repo ref to test"
    )
    parser_baseline.set_defaults(func=cmd_baseline)

    parser_patchwork = subparsers.add_parser("patchwork")
    parser_patchwork.add_argument(
        "repo",
        type=str,
        help="Base repo URL"
    )
    parser_patchwork.add_argument(
        "baseurl",
        type=str,
        help="Base URL"
    )
    parser_patchwork.add_argument(
        "project",
        type=str,
        help="Project name"
    )
    parser_patchwork.add_argument(
        "--lastpatch",
        type=str,
        help="Last patch (id for pw1; datetime for pw2)")
    parser_patchwork.add_argument(
        "--restapi",
        help="Use REST API",
        action="store_true",
        default=False
    )
    parser_patchwork.add_argument(
        "--apikey",
        type=str,
        help="API key to write down results"
    )
    parser_patchwork.add_argument(
        "--filter",
        type=str,
        help="Patchset filter program"
    )
    parser_patchwork.add_argument(
        '--skip',
        nargs='+',
        default=[],
        help='Patterns of patch names which should be skipped for testing, '
        'case insensitive'
    )
    parser_patchwork.set_defaults(func=cmd_patchwork)

    parser_testinfo = subparsers.add_parser("testinfo")
    parser_testinfo.set_defaults(func=cmd_testinfo)

    # Standalone reporting of already finished testing
    parser_report = subparsers.add_parser('report')
    parser_report.add_argument(
        '--assets',
        type=str,
        help='Directory of assets to report.'
    )
    parser_report.set_defaults(func=cmd_report)

    return parser


def setup_logging(verbose):
    """
    Setup the root logger.

    Args:
        verbose:    Verbosity level to setup log message filtering at.
    """
    logger = logging.getLogger()
    logging.basicConfig(
        format="[%(process)d] %(asctime)s %(levelname)8s   %(message)s"
    )
    logger.setLevel(logging.WARNING - (verbose * 10))
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def cmd_baseline(sw, cfg):
    logging.info("checking baseline: %s [%s]", cfg.get("repo"), cfg.get("ref"))
    sw.set_baseline(cfg.get("repo"), cfg.get("ref"), cfg.get("cfgurl"))
    sw.check_baseline()


def cmd_patchwork(sw, cfg):
    logging.info("checking patchwork: %s [%s]", cfg.get("baseurl"),
                 cfg.get("project"))
    sw.set_baseline(cfg.get("repo"), cfgurl=cfg.get("cfgurl"))
    sw.set_restapi(cfg.get("restapi"))
    sw.add_pw(cfg.get("baseurl"), cfg.get("project"), cfg.get("lastpatch"),
              cfg.get("apikey"), cfg.get('skip'))
    sw.check_patchwork()


def cmd_testinfo(sw, cfg):
    db = sw.db
    db.dump_baserepo_info()


def cmd_report(cfg):
    report = sktm.reporter.MailReporter(cfg.get('assets'),
                                        cfg.get('mail_from'),
                                        cfg.get('mail_to'),
                                        cfg.get('report_intro'),
                                        cfg.get('report_footer'),
                                        smtp_url=cfg.get('smtp_url'),
                                        headers=cfg.get('mail_header'))
    report.create_report()
    report.send_report()


def load_config(args):
    """
    Load sktm configuration from the command line and the configuration file.

    Args:
        args:   Parsed command-line configuration, including the path to the
                configuration file.

    Returns:
        Loaded configuration dictionary.
    """
    config = ConfigParser.ConfigParser()
    config.read(os.path.expanduser(args.rc))
    cfg = vars(args)

    if config.has_section('config'):
        for (name, value) in config.items('config'):
            if name not in cfg or cfg.get(name) is None:
                cfg[name] = value

    if not cfg.get('report_intro'):
        cfg['report_intro'] = DEFAULT_REPORT_INTRO
    else:
        cfg['report_intro'] = os.path.abspath(cfg['report_intro'])
    if not cfg.get('report_footer'):
        cfg['report_footer'] = DEFAULT_REPORT_FOOTER
    else:
        cfg['report_footer'] = os.path.abspath(cfg['report_footer'])

    if not cfg.get('jretry'):
        cfg['jretry'] = DEFAULT_JENKINS_RETRY_COUNT
    else:
        cfg['jretry'] = int(cfg.get('jretry'))

    return cfg


def main():
    """Handle the execution of sktm"""
    parser = setup_parser()
    args = parser.parse_args()

    setup_logging(args.verbose)
    cfg = load_config(args)
    logging.debug("cfg=%s", cfg)

    if args.func == cmd_report:
        cmd_report(cfg)
    else:
        jenkins_project = sktm.jenkins.JenkinsProject(cfg.get("jjname"),
                                                      cfg.get("jurl"),
                                                      cfg.get("jlogin"),
                                                      cfg.get("jpass"),
                                                      cfg.get("jretry"))

        sw = sktm.watcher(jenkins_project, cfg.get("db"),
                          cfg.get("filter"), cfg.get("makeopts"))

        args.func(sw, cfg)
        try:
            sw.wait_for_pending()
        except KeyboardInterrupt:
            logging.info("Quitting...")
            sw.cleanup()


if __name__ == '__main__':
    main()
