import unittest

import october_creative as builder


class CreativeEditIntentTests(unittest.TestCase):
    def test_edit_existing_room_without_rebuilding(self):
        self.assertTrue(builder.is_edit_request("xona ichiga stol qo'sh", True))
        self.assertTrue(builder.is_edit_request("xona rangini ko'k qil", True))

    def test_explicit_new_build_is_not_an_edit(self):
        self.assertFalse(builder.is_edit_request("3D xona yarat", True))
        self.assertFalse(builder.is_edit_request("yangi loyiha qurib ber", True))

    def test_no_existing_project_means_no_edit(self):
        self.assertFalse(builder.is_edit_request("xona ichiga stol qo'sh", False))


if __name__ == "__main__":
    unittest.main()
