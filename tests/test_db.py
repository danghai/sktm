# Copyright (c) 2018 Red Hat, Inc. All rights reserved. This copyrighted
# material is made available to anyone wishing to use, modify, copy, or
# redistribute it subject to the terms and conditions of the GNU General Public
# License v.2 or later.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
"""Tests for the db module."""
import os
import shutil
import sqlite3
import tempfile
import unittest

import mock

from sktm.db import SktDb


class TestDb(unittest.TestCase):  # pylint: disable=too-many-public-methods
    """Test cases for the db module."""

    def setUp(self):
        """Test fixtures for testing __init__."""
        self.database_dir = tempfile.mkdtemp()
        self.database_file = "{}/testing.sqlite".format(self.database_dir)

    def tearDown(self):
        """Destroy test fixtures when testing is complete."""
        shutil.rmtree(self.database_dir)

    def test_db_create_already_exists(self):
        """Ensure SktDb() creates a database file when it doesn't exist."""
        sqlite3.connect(self.database_file)
        SktDb(self.database_file)

        self.assertTrue(os.path.isfile(self.database_file))

    @mock.patch('logging.debug')
    @mock.patch('sktm.db.SktDb._SktDb__get_sourceid')
    @mock.patch('sktm.db.sqlite3')
    def test_commit_patch(self, mock_sql, mock_get_sourceid, mock_log):
        """Ensure __commit_patch() creates/updates a patch record."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_get_sourceid.return_value = '1'
        testdb._SktDb__commit_patch('1', '2', '3', '4', '5', '6', '7')

        # Check if we have a proper INSERT query executed
        execute_call_args = mock_sql.connect().cursor().execute.call_args[0]
        self.assertIn('INSERT OR REPLACE INTO patch', execute_call_args[0])
        self.assertTupleEqual(
            ('1', '2', '3', '1', '4', '7'),
            execute_call_args[1]
        )

        mock_log.assert_called()

        # Ensure the data was committed to the database
        mock_sql.connect().commit.assert_called()

    @mock.patch('logging.debug')
    @mock.patch('sktm.db.SktDb._SktDb__commit_patch')
    @mock.patch('sktm.db.SktDb._SktDb__get_sourceid')
    @mock.patch('sktm.db.sqlite3')
    def test_commit_series_without_id(self, mock_sql, mock_get_sourceid,
                                      mock_commit_patch, mock_log):
        """Ensure __commit_series() creates patch records without series_id."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)

        mock_get_sourceid.return_value = '1'
        mock_commit_patch.return_value = None
        mock_sql.connect().cursor().fetchone.return_value = [10]

        patches = [(['patch_id'], 'patch_name', 'patch_url', 'base_url',
                    'project_id', 'patch_date')]
        result = testdb._SktDb__commit_series(patches, None)

        self.assertEqual(result, 11)

        # Check if we have a proper SELECT query executed for the series_id
        # lookup
        execute_call_args = mock_sql.connect().cursor().execute.call_args[0]
        self.assertIn('SELECT series_id FROM patch', execute_call_args[0])

        mock_get_sourceid.assert_called_once()
        mock_commit_patch.assert_called_once()
        mock_log.assert_called()

        # Ensure the data was committed to the database
        mock_sql.connect().commit.assert_called()

    @mock.patch('logging.debug')
    @mock.patch('sktm.db.SktDb._SktDb__commit_patch')
    @mock.patch('sktm.db.SktDb._SktDb__get_sourceid')
    @mock.patch('sktm.db.sqlite3')
    def test_commit_series_without_id_empty_db(self, mock_sql,
                                               mock_get_sourceid,
                                               mock_commit_patch, mock_log):
        """Ensure __commit_series() creates patch records with empty testdb."""
        # pylint: disable=invalid-name,W0212,E1101
        testdb = SktDb(self.database_file)

        mock_get_sourceid.return_value = '1'
        mock_commit_patch.return_value = None
        mock_sql.connect().cursor().fetchone.return_value = None

        patches = [(['patch_id'], 'patch_name', 'patch_url', 'base_url',
                    'project_id', 'patch_date')]
        result = testdb._SktDb__commit_series(patches, None)

        self.assertEqual(result, 1)

        # Check if we have a proper SELECT query executed for the series_id
        # lookup
        execute_call_args = mock_sql.connect().cursor().execute.call_args[0]
        self.assertIn('SELECT series_id FROM patch', execute_call_args[0])

        mock_get_sourceid.assert_called_once()
        mock_commit_patch.assert_called_once()
        mock_log.assert_called()

        # Ensure the data was committed to the database
        mock_sql.connect().commit.assert_called()

    @mock.patch('logging.debug')
    @mock.patch('sktm.db.SktDb._SktDb__commit_patch')
    @mock.patch('sktm.db.SktDb._SktDb__get_sourceid')
    @mock.patch('sktm.db.sqlite3')
    def test_commit_series_with_id(self, mock_sql, mock_get_sourceid,
                                   mock_commit_patch, mock_log):
        """Ensure __commit_series() creates patch records with a series_id."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)

        mock_get_sourceid.return_value = '1'
        mock_commit_patch.return_value = None

        patches = [(['patch_id'], 'patch_name', 'patch_url', 'base_url',
                    'project_id', 'patch_date')]
        result = testdb._SktDb__commit_series(patches, 10)

        self.assertEqual(result, 10)

        mock_get_sourceid.assert_called_once()
        mock_commit_patch.assert_called_once()
        mock_log.assert_called()

        # Ensure the data was committed to the database
        mock_sql.connect().commit.assert_called()

    @mock.patch('logging.debug')
    @mock.patch('sktm.db.sqlite3')
    def test_commit_testrun(self, mock_sql, mock_log):
        """Ensure __commit_testrun() creates a testrun record."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)

        result = mock.Mock()
        result.value = 'ok'

        mock_sql.connect().cursor().lastrowid = 1
        result = testdb._SktDb__commit_testrun(result, '2')

        self.assertEqual(result, 1)

        # Check if we have a proper INSERT query executed
        execute_call_args = mock_sql.connect().cursor().execute.call_args[0]
        self.assertIn('INSERT INTO testrun', execute_call_args[0])
        self.assertTupleEqual(
            ('ok', '2'),
            execute_call_args[1]
        )

        mock_log.assert_called()

        # Ensure the data was committed to the database
        mock_sql.connect().commit.assert_called()

    @mock.patch('sktm.db.sqlite3')
    def test_create_repoid(self, mock_sql):
        """Ensure __create_repoid() inserts into DB and retrieves a repoid."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().lastrowid = 1
        result = testdb._SktDb__create_repoid('git://example.com/repo')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.sqlite3')
    def test_get_baselineid(self, mock_sql):
        """Ensure __get_baselineid() returns baseline_id."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = [1]
        result = testdb._SktDb__get_baselineid('baserepo_id', 'abcdef')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.sqlite3')
    def test_get_baselineid_empty(self, mock_sql):
        """Ensure __get_baselineid() returns None when
           no baseline_id exists."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = None
        result = testdb._SktDb__get_baselineid('baserepo_id', 'abcdef')

        self.assertIsNone(result)

    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_get_baselineresult(self, mock_sql, mock_get_repoid):
        """Ensure __get_baselineresult() returns baseline_id."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_get_repoid.return_value = 1
        mock_sql.connect().cursor().fetchone.return_value = [1]
        result = testdb._SktDb__get_baselineresult('baserepo_id', 'abcdef')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_get_baselineresult_empty(self, mock_sql, mock_get_repoid):
        """Ensure __get_baselineresult() returns None for empty results."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_get_repoid.return_value = 1
        mock_sql.connect().cursor().fetchone.return_value = None
        result = testdb._SktDb__get_baselineresult('baserepo_id', 'abcdef')

        self.assertIsNone(result)

    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_get_commitdate(self, mock_sql, mock_get_repoid):
        """Ensure __get_commitdate() returns baseline_id."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_get_repoid.return_value = 1

        mock_sql.connect().cursor().fetchone.return_value = [1]
        result = testdb._SktDb__get_commitdate('baserepo', 'abcdef')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_get_commitdate_empty(self, mock_sql, mock_get_repoid):
        """Ensure __get_commitdate() returns None when no baselines match."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_get_repoid.return_value = 1
        mock_sql.connect().cursor().fetchone.return_value = None
        result = testdb._SktDb__get_commitdate('baserepod', 'abcdef')

        self.assertIsNone(result)

    @mock.patch('logging.info')
    @mock.patch('sktm.db.SktDb._SktDb__get_sourceid')
    @mock.patch('sktm.db.sqlite3')
    def test_expired_pending_patches(self, mock_sql, mock_get_sourceid,
                                     mock_log):
        """Test with a list of expired pending patches."""
        # pylint: disable=invalid-name
        testdb = SktDb(self.database_file)

        mock_get_sourceid.return_value = '1'

        mock_sql.connect().cursor().fetchall.return_value = ['1']
        result = testdb.get_expired_pending_patches('baseurl', 'project_id')

        self.assertEqual(result, ['1'])
        mock_log.assert_called_once()

    @mock.patch('sktm.db.SktDb._SktDb__get_sourceid')
    @mock.patch('sktm.db.sqlite3')
    def test_expired_pending_patches_empty(self, mock_sql, mock_get_sourceid):
        """Test with an empty list of expired pending patches."""
        # pylint: disable=invalid-name
        testdb = SktDb(self.database_file)

        mock_get_sourceid.return_value = '1'

        mock_sql.connect().cursor().fetchall.return_value = []
        result = testdb.get_expired_pending_patches('baseurl', 'project_id')

        self.assertEqual(result, [])

    @mock.patch('sktm.db.sqlite3')
    def test_last_checked_patch(self, mock_sql):
        """Ensure get_last_checked_patch() returns a patch id."""
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = [1]
        result = testdb.get_last_checked_patch('baseurl', 'project_id')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.sqlite3')
    def test_last_checked_patch_missing(self, mock_sql):
        """Ensure None is returned when no patches match."""
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = None
        result = testdb.get_last_checked_patch('baseurl', 'project_id')

        self.assertIsNone(result)

    @mock.patch('sktm.db.sqlite3')
    def test_pending_patch_date(self, mock_sql):
        """Ensure get_last_pending_patch_date() returns a patch id."""
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = ['2018-05-31']
        result = testdb.get_last_pending_patch_date('baseurl', 'project_id')

        self.assertEqual(result, '2018-05-31')

    @mock.patch('sktm.db.sqlite3')
    def test_pending_patch_date_missing(self, mock_sql):
        """Ensure None is returned when no patches match."""
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = None
        result = testdb.get_last_pending_patch_date('baseurl', 'project_id')

        self.assertIsNone(result)

    @mock.patch('sktm.db.sqlite3')
    def test_checked_patch_date(self, mock_sql):
        """Ensure get_last_checked_patch_date() returns a date."""
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = [1]
        result = testdb.get_last_checked_patch_date('baseurl', 'project_id')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.sqlite3')
    def test_checked_patch_date_missing(self, mock_sql):
        """Ensure None is returned when no patches match."""
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = None
        result = testdb.get_last_checked_patch_date('baseurl', 'project_id')

        self.assertIsNone(result)

    @mock.patch('sktm.db.sqlite3')
    def test_last_pending_patch(self, mock_sql):
        """Ensure get_last_pending_patch() returns a patch id."""
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = [1]
        result = testdb.get_last_pending_patch('baseurl', 'project_id')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.sqlite3')
    def test_last_pending_patch_missing(self, mock_sql):
        """Ensure None is returned when no patches match."""
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = None
        result = testdb.get_last_pending_patch('baseurl', 'project_id')

        self.assertIsNone(result)

    @mock.patch('sktm.db.sqlite3')
    def test_get_repoid(self, mock_sql):
        """Ensure __get_repoid() retrieves a repoid."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = [1]
        result = testdb._SktDb__get_repoid('git://example.com/repo')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_get_latest(self, mock_sql, mock_get_repoid):
        """Ensure __get_latest() returns a result."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_get_repoid.return_value = 1
        mock_sql.connect().cursor().fetchone.return_value = [1]
        result = testdb._SktDb__get_latest('baserepo_id')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_get_latest_empty(self, mock_sql, mock_get_repoid):
        """Ensure __get_latest() returns None when results are empty."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_get_repoid.return_value = 1
        mock_sql.connect().cursor().fetchone.return_value = None
        result = testdb._SktDb__get_latest('baserepo_id')

        self.assertIsNone(result)

    @mock.patch('sktm.db.sqlite3')
    def test_get_repoid_missing(self, mock_sql):
        """Ensure __get_repoid() creates a repoid when it doesn't exist."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = None
        mock_sql.connect().cursor().lastrowid = 1
        result = testdb._SktDb__get_repoid('git://example.com/repo')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.sqlite3')
    def test_get_sourceid(self, mock_sql):
        """Ensure __get_sourceid() retrieves a patchsource id."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = [1]
        result = testdb._SktDb__get_sourceid('git://example.com/repo', 10)

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.sqlite3')
    def test_get_sourceid_missing(self, mock_sql):
        """Ensure __get_sourceid() creates patchsource when
           it doesn't exist."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_sql.connect().cursor().fetchone.return_value = None
        mock_sql.connect().cursor().lastrowid = 1
        result = testdb._SktDb__get_sourceid('git://example.com/repo', 10)

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_get_stable(self, mock_sql, mock_get_repoid):
        """Ensure get_stable() returns baseline_id."""
        testdb = SktDb(self.database_file)
        mock_get_repoid.return_value = 1
        mock_sql.connect().cursor().fetchone.return_value = [1]
        result = testdb.get_stable('baserepo_id')

        self.assertEqual(result, 1)

    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_get_stable_empty(self, mock_sql, mock_get_repoid):
        """Ensure get_stable() returns None when results are empty."""
        testdb = SktDb(self.database_file)
        mock_get_repoid.return_value = 1
        mock_sql.connect().cursor().fetchone.return_value = None
        result = testdb.get_stable('baserepo_id')

        self.assertIsNone(result)

    @mock.patch('logging.debug')
    @mock.patch('sktm.db.sqlite3')
    def test_set_patchset_pending(self, mock_sql, mock_log):
        """Ensure patches are added to the pendingpatch table."""
        testdb = SktDb(self.database_file)
        testdb.set_patchset_pending('baseurl', '1', [('1', '2018-06-04')])

        mock_sql.connect().cursor().executemany.assert_called_once()
        mock_sql.connect().commit.assert_called()
        mock_log.assert_called_once()

        # Check if we have a proper INSERT query executed
        execute_call_args = mock_sql.connect().cursor().executemany.\
            call_args[0]
        self.assertIn(
            'INSERT OR REPLACE INTO pendingpatches',
            execute_call_args[0]
        )

    @mock.patch('logging.debug')
    @mock.patch('sktm.db.SktDb._SktDb__get_sourceid')
    @mock.patch('sktm.db.sqlite3')
    def test_unset_patchset_pending(self, mock_sql, mock_get_sourceid,
                                    mock_log):
        """Ensure patches are removed from the pendingpatch table."""
        # pylint: disable=W0212,E1101
        testdb = SktDb(self.database_file)
        mock_get_sourceid.return_value = 1

        testdb._SktDb__unset_patchset_pending('baseurl', ['1'])

        # Ensure a debug log was written
        mock_log.assert_called_once()

        # Check if we have a proper DELETE query executed
        execute_call_args = mock_sql.connect().cursor().executemany.\
            call_args[0]
        self.assertIn('DELETE FROM pendingpatches', execute_call_args[0])
        self.assertEqual([('baseurl', '1')], execute_call_args[1])

        # Ensure the data was committed to the database
        mock_sql.connect().commit.assert_called()

    @mock.patch('logging.debug')
    @mock.patch('sktm.db.SktDb._SktDb__get_baselineresult')
    @mock.patch('sktm.db.SktDb._SktDb__commit_testrun')
    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_update_baseline_new(self, mock_sql, mock_get_repoid,
                                 mock_commit_testrun, mock_get_baselineresult,
                                 mock_log):
        """Ensure new baslines are created when one doesn't exist."""
        # pylint: disable=too-many-arguments
        testdb = SktDb(self.database_file)

        mock_get_repoid.return_value = '1'
        mock_commit_testrun.return_value = '1'
        mock_get_baselineresult.return_value = None

        testdb.update_baseline('baserepo', 'abcdef', '2018-06-01', '1', '1')

        # Ensure a debug log was written
        mock_log.assert_called()

        # Check if we have a proper INSERT query executed
        execute_call_args = mock_sql.connect().cursor().execute.call_args[0]
        self.assertIn('INSERT INTO baseline', execute_call_args[0])
        self.assertTupleEqual(
            ('1', 'abcdef', '2018-06-01', '1'),
            execute_call_args[1]
        )

        # Ensure the data was committed to the database
        mock_sql.connect().commit.assert_called()

    @mock.patch('logging.debug')
    @mock.patch('sktm.db.SktDb._SktDb__get_baselineresult')
    @mock.patch('sktm.db.SktDb._SktDb__commit_testrun')
    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_update_baseline(self, mock_sql, mock_get_repoid,
                             mock_commit_testrun, mock_get_baselineresult,
                             mock_log):
        """Ensure baseline is updated when current result is newer."""
        # pylint: disable=too-many-arguments
        testdb = SktDb(self.database_file)

        mock_get_repoid.return_value = '1'
        mock_commit_testrun.return_value = '1'
        mock_get_baselineresult.return_value = 1

        testdb.update_baseline('baserepo', 'abcdef', '2018-06-01', '2', '1')

        # Ensure a debug log was written
        mock_log.assert_called()

        # Check if we have a proper INSERT query executed
        execute_call_args = mock_sql.connect().cursor().execute.call_args[0]
        self.assertIn('UPDATE baseline', execute_call_args[0])
        self.assertTupleEqual(
            ('1', 'abcdef', '1'),
            execute_call_args[1]
        )

        # Ensure the data was committed to the database
        mock_sql.connect().commit.assert_called()

    @mock.patch('logging.debug')
    @mock.patch('sktm.db.SktDb._SktDb__get_baselineresult')
    @mock.patch('sktm.db.SktDb._SktDb__commit_testrun')
    @mock.patch('sktm.db.SktDb._SktDb__get_repoid')
    @mock.patch('sktm.db.sqlite3')
    def test_update_baseline_not_newer(self, mock_sql, mock_get_repoid,
                                       mock_commit_testrun,
                                       mock_get_baselineresult, mock_log):
        """Ensure baseline is updated when current result is older."""
        # pylint: disable=too-many-arguments
        testdb = SktDb(self.database_file)

        mock_sql.reset_mock()
        mock_get_repoid.return_value = '1'
        mock_commit_testrun.return_value = '1'
        mock_get_baselineresult.return_value = 2

        testdb.update_baseline('baserepo', 'abcdef', '2018-06-01', 1, '1')

        # Ensure a debug log was written
        mock_log.assert_called()

        # Ensure we didn't execute any SQL queries or run a commit
        mock_sql.connect().cursor().execute.assert_not_called()
        mock_sql.connect().commit.assert_not_called()
