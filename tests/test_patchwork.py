# coding=utf-8
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
"""Tests for the patchwork module."""
import logging
import unittest

from sktm import patchwork

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.DEBUG)


class TestPatchworkFunctions(unittest.TestCase):
    """Test cases for functions in patchwork.py."""

    def test_stringify_integer(self):
        """Ensure stringify converts non-strings to strings."""
        test_integer = 123456
        result = patchwork.stringify(test_integer)
        self.assertEqual(str(test_integer), result)

    def test_stringify_unicode(self):
        """Ensure stringify handles unicode strings."""
        unicode_string = u'☃'
        self.assertEqual('\xe2\x98\x83', patchwork.stringify(unicode_string))


class TestObjectSummary(unittest.TestCase):
    """Test cases for the ObjectSummary class."""

    # pylint: disable=too-many-public-methods

    def setUp(self):
        """Test fixtures for testing __init__."""
        self.test_url = 'http://example.com/patch/2'
        self.testobj = patchwork.ObjectSummary(
            url=self.test_url,
            mbox_sfx='mbox',
            date='2018-06-04',
            patch_id=1
        )

    def test_is_patch_true(self):
        """Ensure the __is_patch() method returns true if patch_id set."""
        # pylint: disable=W0212,E1101
        result = self.testobj._ObjectSummary__is_patch()
        self.assertTrue(result)

    def test_is_patch_false(self):
        """Ensure the __is_patch() method returns false if patch_id not set."""
        # pylint: disable=W0212,E1101
        self.testobj.patch_id = None
        result = self.testobj._ObjectSummary__is_patch()
        self.assertFalse(result)

    def test_get_mbox_url(self):
        """Ensure get_mbox_url() appends '/mbox' to the URL."""
        result = self.testobj.get_mbox_url()
        self.assertEqual("{}/mbox".format(self.test_url), result)


class TestSeriesSummary(unittest.TestCase):
    """Test cases for the SeriesSummary class."""

    # pylint: disable=too-many-public-methods

    def setUp(self):
        """Test fixtures for testing __init__."""
        self.testobj = patchwork.SeriesSummary()

    def tearDown(self):
        """Destroy test fixtures when testing is complete."""
        pass

    def test_set_message_id(self):
        """Ensure the Message-Id header is set."""
        test_value = "Testing Message ID"
        self.testobj.set_message_id(test_value)
        self.assertEqual(test_value, self.testobj.message_id)

    def test_set_subject(self):
        """Ensure the Subject of the series is set."""
        test_value = "Testing Subject"
        self.testobj.set_subject(test_value)
        self.assertEqual(test_value, self.testobj.subject)

    def test_set_cover_letter(self):
        """Ensure the cover letter of the series is set."""
        test_value = "Cover letter"
        self.testobj.set_cover_letter(test_value)
        self.assertEqual(test_value, self.testobj.cover_letter)

    def test_merge_email_addr_set(self):
        """Ensure the merge_email_addr_set() method merges addresses."""
        # Try adding the first email address
        test_value = set(["a@example.com"])
        self.testobj.merge_email_addr_set(test_value)
        self.assertEqual(test_value, self.testobj.email_addr_set)

        # Try adding the second email address
        test_value_extra = set(["b@example.com"])
        self.testobj.merge_email_addr_set(test_value_extra)
        expected_set = set([list(test_value)[0], list(test_value_extra)[0]])
        self.assertSetEqual(expected_set, self.testobj.email_addr_set)

    def test_add_patch(self):
        """Ensure new patches are appended to the patch list."""
        # Patch list should be empty
        self.assertEqual([], self.testobj.patch_list)

        # Add a patch and check
        self.testobj.add_patch('patch1')
        self.assertEqual(['patch1'], self.testobj.patch_list)

        # Add a second patch and check
        self.testobj.add_patch('patch2')
        self.assertEqual(['patch1', 'patch2'], self.testobj.patch_list)

    def test_is_empty(self):
        """Ensure that is_empty() can check if patch_list is empty."""
        # Patch list should be empty before adding patches
        self.assertTrue(self.testobj.is_empty())

        # Add a patch and test
        self.testobj.add_patch('patch1')
        self.assertFalse(self.testobj.is_empty())

    def test_get_patch_info_list(self):
        """Ensure get_patch_info_list() makes a list of tuples."""
        patch_data = patchwork.ObjectSummary('url', 'mbox', '2018-06-04', '1')
        self.testobj.add_patch(patch_data)

        result = self.testobj.get_patch_info_list()

        self.assertEqual([('1', '2018-06-04')], result)

    def test_get_patch_url_list(self):
        """Ensure get_patch_url_list() returns a list of patch URLs."""
        patch_data = patchwork.ObjectSummary('url', 'mbox', '2018-06-04', '1')
        self.testobj.add_patch(patch_data)

        result = self.testobj.get_patch_url_list()

        self.assertEqual(['url'], result)

    def test_get_patch_mbox_url_list(self):
        """Ensure get_patch_mbox_url_list() returns a list of patch URLs."""
        patch_data = patchwork.ObjectSummary('url', 'mbox', '2018-06-04', '1')
        self.testobj.add_patch(patch_data)

        result = self.testobj.get_patch_mbox_url_list()

        self.assertEqual(['url/mbox'], result)
