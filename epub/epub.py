"""
Function-style checkers for file formats. Does the same as mime-magic do
"""
import logging
import os
import re
import zipfile
from io import IOBase

from bs4 import BeautifulSoup
from lxml import etree, html


log = logging.getLogger(__name__)


class InvalidFileException(Exception):
    pass


class InvalidEpubException(InvalidFileException):
    pass



def check_zip(f):
    """
    Returns `True` if file is a valid zip
    :param f:
    :return:
    """
    try:
        zf = zipfile.ZipFile(f)
        file = os.path.splitext(str(f))[0]
        p = etree.parse(zf.open(file), parser=etree.XMLParser(resolve_entities=False))
        if 'FictionBook' in p.getroot().tag:
            return True
    except Exception:
        return False


def flatten(nested, flat):
    for i in nested:
        flatten(i, flat) if isinstance(i, list) else flat.append(i)
    return flat


def xml_from_string(xml):
    """
    Django stores document data in unicode, but lxml doesn't like that if the
    document itself contains an encoding declaration, so convert from unicode
    first if necessary.
    """
    parser = etree.XMLParser(resolve_entities=False)
    if isinstance(xml, str):
        xml = xml.encode('utf-8')
    if isinstance(xml, bytes):
        try:
            return etree.fromstring(xml, parser=parser)
        except etree.XMLSyntaxError:
            raise InvalidEpubException('Unable to parse file')
    return etree.fromstring(xml, parser=parser)


def html_from_string(content):
    parser = html.HTMLParser(recover=True, remove_blank_text=False)
    if isinstance(content, str):
        content = content.encode('utf-8')
    if isinstance(content, bytes):
        try:
            return html.document_fromstring(content, parser=parser)
        except etree.XMLSyntaxError:
            raise InvalidEpubException('Unable to parse file')
    return html.document_fromstring(content, parser=parser)


def is_xml_text(obj):
    if hasattr(obj, 'is_text') and obj.is_text:
        return True
    elif isinstance(obj, etree._ElementUnicodeResult):
        return True
    elif isinstance(obj, etree._ElementStringResult):
        return True
    elif isinstance(obj, (str, bytes)):
        return True
    return False


class Epub:
    book_type = 'epub'
    CONTAINER = 'META-INF/container.xml'

    MARK = 'SPEC_MARK_FOR_SELECT'  # mark for select text in xml tree

    NS = {
        'container': 'urn:oasis:names:tc:opendocument:xmlns:container',
        'opf': 'http://www.idpf.org/2007/opf',
        'dc': 'http://purl.org/dc/elements/1.1/',
        'ncx': 'http://www.daisy.org/z3986/2005/ncx/',
        'html': 'http://www.w3.org/1999/xhtml',
        'dtbook': 'http://www.daisy.org/z3986/2005/dtbook/',
        're': 'http://exslt.org/regular-expressions'
    }

    DC_TITLE_TAG = 'title'
    DC_CREATOR_TAG = 'creator'
    DC_LANGUAGE_TAG = 'language'
    DC_RIGHTS_TAG = 'rights'
    DC_SUBJECT_TAG = 'subject'
    DC_PUBLISHER_TAG = 'publisher'
    DC_IDENTIFIER_TAG = 'identifier'
    DC_DESCRIPTION_TAG = 'description'
    DC_COVER_TAG = 'cover'

    COVERIMAGE_TYPES = ('jpeg', 'png', 'svg', 'jpg')

    def __init__(self, fl):
        if isinstance(fl, IOBase) or hasattr(fl, 'file'):
            self._file = fl
            needs_closing = False
        else:
            self._file = open(fl)
            needs_closing = True
        self.check_epub(fl)
        fl_name = self.rootfile.get('full-path')
        with self.zf.open(fl_name) as zip_file:
            self._parsed_metadata = xml_from_string(zip_file.read())
        self.content_path = os.path.split(self.rootfile.get('full-path'))[0]
        self.cover_image_type = 'img'
        self._cover = None
        if needs_closing:
            self._file.close()

    @property
    def name(self):
        return self.get_title(self._parsed_metadata)

    @property
    def author(self):
        authors = self.get_authors(self._parsed_metadata)
        if authors:
            return authors[0]
        else:
            return None

    @property
    def authors(self):
        return self.get_authors(self._parsed_metadata)

    @property
    def publishers(self):
        return self.get_publisher(self._parsed_metadata)

    @property
    def description(self):
        return self.get_description(self._parsed_metadata)

    @property
    def cover_image(self):
        if not self._cover:
            self._cover = self.get_cover(self._parsed_metadata)
        return self._cover

    def get_notes(self):
        return self._parsed_metadata.xpath('/opf:package/opf:guide//opf:reference[@type="notes"]',
                                           namespaces={'opf': self.NS['opf']})

    def check_epub(self, f):
        try:
            self.zf = zipfile.ZipFile(f)
            parser = etree.XMLParser(resolve_entities=False)
            self.container_tree = etree.parse(self.zf.open(self.CONTAINER), parser=parser)
            self.rootfile = self.container_tree.xpath(
                '/e:container/e:rootfiles/e:rootfile',
                namespaces={'e': self.NS['container']})[0]
            media_type = self.rootfile.get('media-type')
            return media_type == 'application/oebps-package+xml'
        except (KeyError, etree.LxmlError, zipfile.BadZipfile):
            raise InvalidEpubException('Is incorrect ePub')

    def get_toc_xml(self):
        toc_path = self.get_toc(self._parsed_metadata, self.content_path)
        return xml_from_string(self.zf.open(toc_path).read())

    def get_table_of_content(self):
        from apps.utils.file_formats.toc import TOC

        toc_path = self.get_toc(self._parsed_metadata, self.content_path)
        return TOC(self.zf.open(toc_path).read())

    @classmethod
    def get_toc(cls, opf, content_path):
        """Parse the opf file to get the name of the TOC
        (From OPF spec: The spine element must include the toc attribute,
        whose value is the the id attribute value of the required NCX document
        declared in manifest)"""
        spine = opf.find(f'.//{cls.NS["opf"]}spine')
        if spine is None:
            raise InvalidEpubException(
                'Could not find an opf:spine element in this document')
        tocid = spine.get('toc')

        if tocid:
            try:
                toc_filename = opf.xpath(f'//opf:item[@id="{tocid}"]',
                                         namespaces={'opf': cls.NS['opf']})[0].get('href')
            except IndexError:
                raise InvalidEpubException(
                    f'Could not find an item matching {tocid} in OPF <item> list')
        else:
            # Find by media type
            try:
                toc_filename = opf.xpath(
                    '//opf:item[@media-type="application/x-dtbncx+xml"]',
                    namespaces={'opf': cls.NS['opf']})[0].get('href')
            except IndexError:
                # Last ditch effort, find an href with the .ncx extension
                try:
                    toc_filename = opf.xpath(
                        '//opf:item[contains(@href, ".ncx")]',
                        namespaces={'opf': cls.NS['opf']})[0].get('href')
                except IndexError:
                    raise InvalidEpubException('Could not find any NCX file.')
        return os.path.join(content_path, toc_filename)

    @classmethod
    def get_authors(cls, opf):
        authors = [
            a.text.strip()
            for a in opf.findall(f'.//{cls.NS["dc"]}{cls.DC_CREATOR_TAG}')
            if a is not None and a.text is not None
        ]
        return authors

    @classmethod
    def get_title(cls, xml):
        title = xml.xpath(
            '/opf:package/opf:metadata//dc:title/text()', namespaces={'opf': cls.NS['opf'],
                                                                      'dc': cls.NS['dc']})
        if not len(title):
            raise InvalidEpubException('This ePub document does not have a title. \
                                According to the ePub specification, all documents must have a title.')

        return title[0].strip()

    @classmethod
    def get_publishers(cls, opf):
        value = cls._get_metadata(cls.DC_PUBLISHER_TAG, opf, plural=True)
        if not value:
            return None
        return [s for s in value]

    @classmethod
    def get_description(cls, opf):
        return cls._get_metadata(cls.DC_DESCRIPTION_TAG, opf, as_string=True)

    @classmethod
    def get_language(cls, opf):
        language = cls._get_metadata(cls.DC_LANGUAGE_TAG, opf, as_string=True)
        if language != '':
            return language
        else:
            return None

    @classmethod
    def get_major_language(cls, opf):
        lang = cls.get_language(opf)
        if not lang:
            return None
        if '-' in lang or '_' in lang:
            for div in ('-', '_'):
                if div in lang:
                    return lang.split(div)[0]
        return lang

    @classmethod
    def get_rights(cls, opf):
        rights = cls._get_metadata(cls.DC_RIGHTS_TAG, opf, as_string=True)
        if rights != '':
            return rights
        else:
            return None

    @classmethod
    def get_publisher(cls, opf):
        publisher = cls._get_metadata(cls.DC_PUBLISHER_TAG, opf)
        if not publisher:
            return None
        return publisher

    def get_cover(self, xml):
        def _take_cover(path):
            xml.xpath(path, namespaces={'opf': self.NS['opf'], 'dc': self.NS['dc']})

        cover_paths = [
            '/opf:package/opf:manifest/opf:item[contains(@id, "cover") and contains(@media-type, "image")]',
        ]

        for path in cover_paths:
            elements = _take_cover(path)
            if elements:
                break
        else:
            return None

        filename = os.path.join(self.content_path, elements[0].get('href'))
        self.cover_image_type = elements[0].get('media-type').split('/')[1]
        if self.cover_image_type not in self.COVERIMAGE_TYPES:
            raise InvalidEpubException(f'Cover image incorrect format: {self.cover_image_type}')
        content = self.zf.open(filename).read()

        return content

    def get_part_content(self, part):
        file_address = self._parsed_metadata.xpath(f"/opf:package/opf:manifest/opf:item[@id='{part}']/@href",
                                                   namespaces={'opf': self.NS['opf'],
                                                               'dc': self.NS['dc']})[0]
        with self.zf.open(f'OEBPS/{file_address}') as zip_file:
            content = zip_file.read()
        return content

    @classmethod
    def valid_citation(cls, content, cite, start_xpath, start_offset, end_xpath, end_offset):
        TEXT_NODE = 'TEXT_NODE'
        RE_ENTER = r'\s*\r?\n\s*'

        _content = re.sub(fr'(?P<br1><br[^>]*>)\s*(?P<br2><br[^>]*>)',
                          fr'\g<br1>{TEXT_NODE}\g<br2>', content)
        parsed_html = html_from_string(_content)

        default_xpath_prefix = '/html/body/'

        start_xpath = default_xpath_prefix + start_xpath.lower()
        end_xpath = default_xpath_prefix + end_xpath.lower()

        parent = cls.get_mutural_parent(parsed_html, start_xpath, end_xpath)
        txt = parent.text_content()
        text = re.sub(RE_ENTER, '', txt).replace(TEXT_NODE, '').replace('\u2005', ' ')
        cite = re.sub(RE_ENTER, '', cite).replace('\u2005', ' ')
        return cite in text

    @classmethod
    def text(cls, content, start_xpath, start_offset, end_xpath, end_offset):
        TEXT_NODE = 'TEXT_NODE'
        _content = re.sub(fr'(?P<br1><br[^>]*>)\s*(?P<br2><br[^>]*>)',
                          fr'\g<br1>{TEXT_NODE}\g<br2>', content)
        parsed_html = html_from_string(_content)

        default_xpath_prefix = '/html/body/'

        start_xpath = default_xpath_prefix + start_xpath.lower()
        end_xpath = default_xpath_prefix + end_xpath.lower()

        try:
            start_elem = parsed_html.xpath(start_xpath)[0]
            end_elem = parsed_html.xpath(end_xpath)[0]
        except IndexError:
            return ''

        parent = cls.get_mutural_parent(parsed_html, start_xpath, end_xpath)
        txt = parent.text_content()

        if is_xml_text(start_elem) and is_xml_text(end_elem):

            if start_elem == end_elem:
                return cls.unescape(start_elem[start_offset:end_offset])

            start_elem_index = cls.get_elem_index(
                parent, txt, start_elem, offset=start_offset)
            end_elem_index = cls.get_elem_index(parent, txt, end_elem)
            result = txt[start_elem_index:end_elem_index + len(
                end_elem[:end_offset])]

        elif is_xml_text(start_elem) and not is_xml_text(end_elem):
            full_end_xpath = end_xpath + '/node()'
            elements = parsed_html.xpath(full_end_xpath)
            start_elem_index = cls.get_elem_index(
                parent, txt, start_elem, offset=start_offset)
            end_text = cls.get_text_from_elements_list(elements[:end_offset])
            end_elem_index = txt.find(end_text)
            result = txt[start_elem_index:end_elem_index + len(end_text)]

        elif not is_xml_text(start_elem) and is_xml_text(end_elem):
            full_start_xpath = start_xpath + '/node()'
            start_elem = parsed_html.xpath(full_start_xpath)[start_offset]
            start_elem_index = cls.get_elem_index(parent, txt, start_elem)
            end_elem_index = cls.get_elem_index(parent, txt, end_elem)
            result = txt[start_elem_index:end_elem_index + end_offset]

        else:
            full_start_xpath = start_xpath + '/node()'
            full_end_xpath = end_xpath + '/node()'

            start_elements = parsed_html.xpath(full_start_xpath)
            start_text = cls.get_text_from_elements_list(
                start_elements[start_offset:])
            start_elem_index = txt.find(start_text)

            end_elements = parsed_html.xpath(full_end_xpath)
            end_text = cls.get_text_from_elements_list(
                end_elements[:end_offset])
            end_elem_index = txt.find(end_text)
            result = txt[start_elem_index:end_elem_index + len(end_text)]
        return cls.unescape(result.replace(TEXT_NODE, ''))

    @classmethod
    def get_elem_index(cls, parent, txt, element, offset=0):
        if is_xml_text(element):
            element_txt = element
            element = element.getparent()
        else:
            element_txt = element.text_content()

        text_count = txt.count(element_txt)
        if text_count > 1 or is_xml_text(element):
            element_text = element.text
            element.text = cls.MARK
            index = parent.text_content().find(cls.MARK) + offset
            element.text = element_text
        elif text_count == 1:
            index = txt.find(element_txt) + offset
        else:
            index = -1
        return index

    @classmethod
    def get_text_from_elements_list(cls, elements):
        text = ''
        for elem in elements:
            if is_xml_text(elem):
                text = text + elem
            else:
                text = text + elem.text_content()
        return text

    @classmethod
    def get_element_xpath_from_text(cls, xpath):
        if xpath.find('/text()') != -1:
            return xpath[:xpath.find('/text()')]

    @classmethod
    def get_mutural_parent(cls, parsed_html, start_xpath, end_xpath):
        ancestors1 = parsed_html.xpath(start_xpath + '/ancestor-or-self::*')
        ancestors2 = parsed_html.xpath(end_xpath + '/ancestor-or-self::*')

        for pair in zip(ancestors1, ancestors2):
            if pair[0] != pair[1]:
                break
            parent = pair[0]
        return parent

    @classmethod
    def unescape(cls, text):
        return str(BeautifulSoup(text, features='xml'))

    @classmethod
    def unescape_over(cls, text):
        return str(BeautifulSoup(text))

    @classmethod
    def _get_metadata(cls, metadata_tag, opf, plural=False, as_string=False, as_list=False):
        """
        Returns a metdata item's text content by tag name, or a list if mulitple names match.
        If as_string is set to True, then always return a comma-delimited string.
        """
        if isinstance(opf, (str, bytes)):
            parsed_metadata = xml_from_string(opf)
        else:
            parsed_metadata = opf
        text = []
        alltext = parsed_metadata.findall(
            f'.//{cls.NS["dc"]}{metadata_tag}')
        if as_list:
            return [t.text.strip() for t in alltext if t.text]
        if as_string:
            return ', '.join([t.text.strip() for t in alltext if t.text])
        for t in alltext:
            if t.text is not None:
                text.append(t.text)
        if len(text) == 1:
            t = (text[0], ) if plural else text[0]
            return t
        return text
