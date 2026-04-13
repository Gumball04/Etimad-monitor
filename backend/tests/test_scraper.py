import unittest

from app.services.scraper import EtimadProtectionError, EtimadScraper, _raise_for_protection_page


class _NeighborLocator:
    def inner_text(self, timeout=None):
        raise RuntimeError("no sibling")


class _WrapperLocator:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text


class _LabelLocator:
    def __init__(self, wrapper_text):
        self.wrapper_text = wrapper_text

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def locator(self, expr):
        if expr == "xpath=ancestor::*[1]":
            return _WrapperLocator(self.wrapper_text)
        return _NeighborLocator()


class _Page:
    def __init__(self, wrapper_text):
        self.wrapper_text = wrapper_text

    def locator(self, selector):
        return _LabelLocator(self.wrapper_text)


class ScraperTests(unittest.TestCase):
    def test_protection_page_raises_explicit_error(self):
        with self.assertRaises(EtimadProtectionError):
            _raise_for_protection_page("Please enable JavaScript before continuing")

    def test_wrapper_text_extraction_returns_requested_field_only(self):
        scraper = EtimadScraper(keyword="test")
        page = _Page("الغرض من المنافسة: وصف طويل مدة العقد: 30 يوم")

        value = scraper._read_value_near_label(page, "مدة العقد")

        self.assertEqual(value, "30 يوم")


if __name__ == "__main__":
    unittest.main()
