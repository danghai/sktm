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
import logging
import os
import sqlite3
import time
import sktm


class skt_db(object):
    def __init__(self, db):
        if not os.path.isfile(db):
            self.createdb(db)

        self.conn = sqlite3.connect(db)
        self.cur = self.conn.cursor()

    def __del__(self):
        self.conn.close()

    def createdb(self, db):
        tc = sqlite3.connect(db)
        c = tc.cursor()

        # FIXME The "patchsource_id" field should be a part of the primary key
        #       for "pendingpatches" and "patch" tables.
        c.executescript("""
                PRAGMA foreign_keys = on;

                CREATE TABLE baserepo(
                  id INTEGER PRIMARY KEY,
                  url TEXT UNIQUE
                );

                CREATE TABLE patchsource(
                  id INTEGER PRIMARY KEY,
                  baseurl TEXT,
                  project_id INTEGER,
                  date TEXT
                );

                CREATE TABLE patch(
                  id INTEGER PRIMARY KEY,
                  name TEXT,
                  url TEXT,
                  date TEXT,
                  patchsource_id INTEGER,
                  series_id INTEGER,
                  FOREIGN KEY(patchsource_id) REFERENCES patchsource(id)
                );

                CREATE TABLE pendingpatches(
                  id INTEGER PRIMARY KEY,
                  pdate TEXT,
                  patchsource_id INTEGER,
                  timestamp INTEGER,
                  FOREIGN KEY(patchsource_id) REFERENCES patchsource(id)
                );

                CREATE TABLE testrun(
                  id INTEGER PRIMARY KEY,
                  result_id INTEGER,
                  build_id INTEGER
                );

                CREATE TABLE baseline(
                  id INTEGER PRIMARY KEY,
                  baserepo_id INTEGER,
                  commitid TEXT,
                  commitdate INTEGER,
                  testrun_id INTEGER,
                  FOREIGN KEY(baserepo_id) REFERENCES baserepo(id),
                  FOREIGN KEY(testrun_id) REFERENCES testrun(id)
                );

                CREATE TABLE patchtest(
                  id INTEGER PRIMARY KEY,
                  patch_series_id INTEGER,
                  baseline_id INTEGER,
                  testrun_id INTEGER,
                  FOREIGN KEY(baseline_id) REFERENCES baseline(id),
                  FOREIGN KEY(patch_series_id) REFERENCES patch(series_id),
                  FOREIGN KEY(testrun_id) REFERENCES testrun(id)
                );""")

        tc.commit()
        c.close()
        tc.close()

    # FIXME Creation and retrieval should be separate
    def get_repoid(self, baserepo):
        """
        Fetch or create an ID of a baseline Git repo URL.

        Args:
            baserepo:   Baseline Git repo URL to get ID for.

        Returns:
            Located or created integer ID of the baseline Git repo.
        """
        self.cur.execute('SELECT id FROM baserepo WHERE url=?',
                         (baserepo,))

        brid = self.cur.fetchone()
        if brid is not None:
            return brid[0]

        self.cur.execute('INSERT INTO baserepo(url) VALUES(?)',
                         (baserepo,))
        self.conn.commit()
        return self.get_repoid(baserepo)

    # FIXME Creation and retrieval should be separate
    def get_sourceid(self, baseurl, projid):
        """
        Fetch or create an ID of a patch source corresponding to a Patchwork
        base URL and a patchwork project ID.

        Args:
            baseurl:    Patchwork base URL.
            projid:     Patchwork project ID.

        Returns:
            Located or created integer ID of the patch source.
        """
        self.cur.execute('SELECT id FROM patchsource WHERE '
                         'baseurl=? AND '
                         'project_id=?',
                         (baseurl, projid))

        sid = self.cur.fetchone()
        if sid is not None:
            return sid[0]

        self.cur.execute('INSERT INTO patchsource(baseurl, project_id) '
                         'VALUES(?,?)',
                         (baseurl, projid))
        self.conn.commit()
        return self.get_sourceid(baseurl, projid)

    def get_last_checked_patch(self, baseurl, projid):
        sourceid = self.get_sourceid(baseurl, projid)

        self.cur.execute('SELECT patch.id FROM patch WHERE '
                         'patchsource_id = ? '
                         'ORDER BY id DESC LIMIT 1',
                         (sourceid,))
        res = self.cur.fetchone()
        return None if res is None else res[0]

    def get_last_pending_patch(self, baseurl, projid):
        sourceid = self.get_sourceid(baseurl, projid)

        self.cur.execute('SELECT id FROM pendingpatches WHERE '
                         'patchsource_id = ? '
                         'ORDER BY id DESC LIMIT 1',
                         (sourceid,))
        res = self.cur.fetchone()
        return None if res is None else res[0]

    def set_event_date(self, baseurl, projid, date):
        if date is None:
            return
        logging.debug("event date: %s %d -> %s", baseurl, projid, date)
        self.cur.execute('UPDATE patchsource SET date = ? '
                         'WHERE baseurl = ? AND project_id = ?',
                         (date, baseurl, projid))
        self.conn.commit()

    def get_last_event_date(self, baseurl, projid):
        self.cur.execute('SELECT date FROM patchsource WHERE '
                         'baseurl = ? AND project_id = ?',
                         (baseurl, projid))
        res = self.cur.fetchone()
        return None if res is None else res[0]

    def get_last_checked_patch_date(self, baseurl, projid):
        sourceid = self.get_sourceid(baseurl, projid)

        self.cur.execute('SELECT patch.date FROM patch WHERE '
                         'patchsource_id = ? '
                         'ORDER BY date DESC LIMIT 1',
                         (sourceid,))
        res = self.cur.fetchone()
        return None if res is None else res[0]

    def get_last_pending_patch_date(self, baseurl, projid):
        sourceid = self.get_sourceid(baseurl, projid)

        self.cur.execute('SELECT pdate FROM pendingpatches WHERE '
                         'patchsource_id = ? '
                         'ORDER BY pdate DESC LIMIT 1',
                         (sourceid,))
        res = self.cur.fetchone()
        return None if res is None else res[0]

    def get_expired_pending_patches(self, baseurl, projid, exptime=86400):
        """
        Get a list of IDs of patches set as pending for longer than the
        specified time, for a combination of a Patchwork base URL and
        Patchwork project ID.

        Args:
            baseurl:    Base URL of Patchwork instance the project and patches
                        belong to.
            projid:     ID of the Patchwork project the patches belong to.
            exptime:    The longer-than time the returned patches should have
                        been staying in the "pending" list.
                        Default is anything longer than 24 hours.

        Returns:
            List of patch IDs.
        """
        patchlist = list()
        sourceid = self.get_sourceid(baseurl, projid)
        tstamp = int(time.time()) - exptime

        self.cur.execute('SELECT id FROM pendingpatches WHERE '
                         'patchsource_id = ? AND '
                         'timestamp < ?',
                         (sourceid, tstamp))
        for res in self.cur.fetchall():
            patchlist.append(res[0])

        if len(patchlist):
            logging.info("expired pending patches for %s (%d): %s", baseurl,
                         projid, patchlist)

        return patchlist

    def get_baselineid(self, brid, commithash):
        self.cur.execute('SELECT id FROM baseline WHERE '
                         'baserepo_id = ? AND commitid = ?',
                         (brid, commithash))
        res = self.cur.fetchone()
        return None if res is None else res[0]

    def get_commitdate(self, baserepo, commitid):
        brid = self.get_repoid(baserepo)

        self.cur.execute('SELECT commitdate FROM baseline WHERE '
                         'commitid = ? AND '
                         'baserepo_id = ?',
                         (commitid, brid))
        res = self.cur.fetchone()
        return None if res is None else res[0]

    def get_baselineresult(self, baserepo, commithash):
        brid = self.get_repoid(baserepo)

        self.cur.execute('SELECT testrun.result_id FROM baseline, testrun '
                         'WHERE baseline.commitid = ? AND '
                         'baseline.baserepo_id = ? AND '
                         'baseline.testrun_id = testrun.id '
                         'ORDER BY baseline.commitdate DESC LIMIT 1',
                         (commithash, brid))
        res = self.cur.fetchone()
        return None if res is None else sktm.tresult(res[0])

    def get_stable(self, baserepo):
        """
        Get the latest stable commit ID for a baseline Git repo URL.

        Args:
            baserepo:   Baseline Git repo URL.

        Returns:
            Latest stable commit ID, or None, if there are no stable commits.
        """
        brid = self.get_repoid(baserepo)

        self.cur.execute('SELECT commitid FROM baseline, testrun WHERE '
                         'baseline.baserepo_id = ? AND '
                         'baseline.testrun_id = testrun.id AND '
                         'testrun.result_id = 0 '
                         'ORDER BY baseline.commitdate DESC LIMIT 1',
                         (brid, ))

        res = self.cur.fetchone()
        return None if res is None else res[0]

    def get_latest(self, baserepo):
        brid = self.get_repoid(baserepo)

        self.cur.execute('SELECT commitid FROM baseline WHERE '
                         'baserepo_id = ? '
                         'ORDER BY baseline.commitdate DESC LIMIT 1',
                         (brid, ))

        res = self.cur.fetchone()
        return None if res is None else res[0]

    def set_patchset_pending(self, baseurl, projid, patchset):
        """
        Add each specified patch to the list of "pending" patches, with
        specifed patch date, for specified Patchwork base URL and project ID,
        and marked with current timestamp. Replace any previously added
        patches with the same ID (bug: should be "same ID, project ID and
        base URL").

        Args:
            baseurl:    Base URL of the Patchwork instance the project ID and
                        patch IDs belong to.
            projid:     ID of the Patchwork project the patch IDs belong to.
            patchset:   List of info tuples for patches to add to the list,
                        where each tuple contains the patch ID and a free-form
                        patch date string.
        """
        psid = self.get_sourceid(baseurl, projid)
        tstamp = int(time.time())

        logging.debug("setting patches as pending: %s", patchset)

        self.cur.executemany('INSERT OR REPLACE INTO '
                             'pendingpatches(id, pdate, patchsource_id, '
                             'timestamp) '
                             'VALUES(?, ?, ?, ?)',
                             [(pid, pdate, psid, tstamp) for
                              (pid, pdate) in patchset])
        self.conn.commit()

    def unset_patchset_pending(self, baseurl, projid, patchset):
        """
        Remove each specified patch from the list of "pending" patches, for
        the specified Patchwork base URL and project ID.

        Args:
            baseurl:    Base URL of the Patchwork instance the project ID and
                        patch IDs belong to.
            projid:     ID of the Patchwork project the patch IDs belong to.
            patchset:   List of IDs of patches to be removed from the list.
        """
        psid = self.get_sourceid(baseurl, projid)

        logging.debug("removing patches from pending list: %s", patchset)

        self.cur.executemany('DELETE FROM pendingpatches WHERE id = ? '
                             'AND patchsource_id = ?',
                             [(pid, psid) for pid in patchset])
        self.conn.commit()

    def update_baseline(self, baserepo, commithash, commitdate,
                        result, buildid):
        logging.debug("update_baseline: repo=%s; commit=%s; result=%s",
                      baserepo, commithash, result)
        brepoid = self.get_repoid(baserepo)

        testrunid = self.commit_testrun(result, buildid)

        prev_res = self.get_baselineresult(baserepo, commithash)
        logging.debug("previous result: %s", prev_res)
        if prev_res is None:
            self.cur.execute('INSERT INTO '
                             'baseline(baserepo_id, commitid, commitdate, '
                             'testrun_id) VALUES(?,?,?,?)',
                             (brepoid, commithash, commitdate, testrunid))
        elif result >= prev_res:
            self.cur.execute('UPDATE baseline SET testrun_id = ? '
                             'WHERE commitid = ? AND baserepo_id = ?',
                             (testrunid, commithash, brepoid))
        self.conn.commit()

    # FIXME: There is a chance of series_id collisions between different
    # patchwork instances
    def get_series_result(self, series_id):
        self.cur.execute('SELECT testrun.result_id FROM patchtest, testrun '
                         'WHERE patchtest.patch_series_id = ? '
                         'AND patchtest.testrun_id = testrun.id '
                         'LIMIT 1',
                         (series_id, ))

        res = self.cur.fetchone()
        return None if res is None else res[0]

    def commit_patchtest(self, baserepo, commithash, patches, result, buildid,
                         series=None):
        logging.debug("commit_patchtest: repo=%s; commit=%s; patches=%d; "
                      "result=%s", baserepo, commithash, len(patches), result)
        brepoid = self.get_repoid(baserepo)
        baselineid = self.get_baselineid(brepoid, commithash)
        testrunid = self.commit_testrun(result, buildid)
        seriesid = self.commit_series(patches, series)

        for (pid, pname, purl, baseurl, projid, pdate) in patches:
            # TODO: Can accumulate per-project list instead of doing it one by
            # one
            self.unset_patchset_pending(baseurl, projid, [pid])

        self.cur.execute('INSERT INTO '
                         'patchtest(patch_series_id, baseline_id, testrun_id) '
                         'VALUES(?,?,?)',
                         (seriesid, baselineid, testrunid))
        self.conn.commit()

    def commit_testrun(self, result, buildid):
        logging.debug("commit_testrun: result=%s; buildid=%d", result, buildid)
        self.cur.execute('INSERT INTO testrun(result_id, build_id) '
                         'VALUES(?,?)',
                         (result.value, buildid))

        self.cur.execute('SELECT id FROM testrun WHERE result_id=? AND '
                         'build_id=?',
                         (result.value, buildid))

        testrunid = self.cur.fetchone()[0]
        self.conn.commit()

        return testrunid

    def commit_patch(self, pid, pname, purl, sid, baseurl, projid, pdate):
        logging.debug("commit_patch: pid=%s; sid=%s", pid, sid)
        sourceid = self.get_sourceid(baseurl, projid)
        self.cur.execute('INSERT OR REPLACE INTO patch(id, name, url, '
                         'patchsource_id, series_id, date) '
                         'VALUES(?,?,?,?,?,?)',
                         (pid, pname, purl, sourceid, sid, pdate))
        self.conn.commit()

    def commit_series(self, patches, seriesid=None):
        logging.debug("commit_series: %s (%s)", patches, seriesid)
        if seriesid is None:
            seriesid = 1
            self.cur.execute('SELECT series_id FROM patch '
                             'ORDER BY series_id DESC LIMIT 1')
            res = self.cur.fetchone()
            if res is not None:
                seriesid = 1 + res[0]

        for (pid, pname, purl, baseurl, projid, pdate) in patches:
            sourceid = self.get_sourceid(baseurl, projid)
            self.commit_patch(pid, pname, purl, seriesid, baseurl, projid,
                              pdate)

        self.conn.commit()

        return seriesid

    def dump_baseline_tests(self):
        self.cur.execute('SELECT baserepo.url, baseline.commitid, '
                         'testrun.result_id, testrun.build_id '
                         'FROM baseline, baserepo, testrun '
                         'WHERE baseline.baserepo_id = baserepo.id AND '
                         'baseline.testrun_id = testrun.id')

        for (burl, commit, res, buildid) in self.cur.fetchall():
            print("repo url:", burl)
            print("commit id:", commit)
            print("result:", sktm.tresult(res).name)
            print("build id: #", buildid, sep='')
            print("---")

    def dump_baserepo_info(self):
        self.cur.execute('SELECT url FROM baserepo')

        for (burl,) in self.cur.fetchall():
            print("repo url:", burl)
            stable = self.get_stable(burl)
            latest = self.get_latest(burl)
            print("most recent stable commit: {} ({})".format(
                  stable, self.get_commitdate(burl, stable)))
            print("most recent stable commit: {} ({})".format(
                  latest, self.get_commitdate(burl, latest)))
            print("---")
