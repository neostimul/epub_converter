import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from dateutil.parser import parse as parse_date


def epub_info(file_name: Path | str) -> dict[str, Any]:
    def xpath(element, path):
        return element.xpath(
            path,
            namespaces={
                "n": "urn:oasis:names:tc:opendocument:xmlns:container",
                "pkg": "http://www.idpf.org/2007/opf",
                "dc": "http://purl.org/dc/elements/1.1/",
            },
        )[0]

    # prepare to read from the .epub file
    zip_content = zipfile.ZipFile(file_name)

    # find the contents metafile
    content_file_name = xpath(
        etree.fromstring(zip_content.read("META-INF/container.xml")),
        "n:rootfiles/n:rootfile/@full-path",
    )

    # grab the metadata block from the contents metafile
    metadata = xpath(
        etree.fromstring(zip_content.read(content_file_name)), "/pkg:package/pkg:metadata"
    )

    # repackage the data
    result = {}
    infos = ("title", "creator", "language", "date", "identifier")

    for info in infos:
        try:
            # Почему-то иногда не бывает date. Стоит поискать в meta мб.
            result[info] = xpath(metadata, f"dc:{info}/text()")
        except IndexError:
            continue

    return result


def rename_epubs(directory: str, bad_words: tuple | None = None, dry_run: bool = False) -> None:
    paths = Path(directory).rglob("*.epub")

    for path in paths:
        info = epub_info(path)

        new_name = f'{info['title']} - {info['creator']}.epub'

        for bad_word in bad_words:
            new_name = new_name.replace(bad_word, '')

        new_name = new_name.strip(':').strip('/').strip('\\').strip()
        new_name = new_name.replace(':', '.').replace('/', '.').replace('\\', '.').replace(' .', '.')

        # if book_date := info.get('date'):
        #     book_date = parse_date(book_date)
        #     new_name = f'{book_date.strftime('%Y.%m')} {new_name}'

        original_file_name = path.name
        if original_file_name[0].isnumeric():
            # Сохраняем нумерацию, если она была
            new_name = f'{original_file_name.split(' ')[0]} {new_name}'

        new_path = Path(path.parent, new_name)
        if new_path.is_file() and path != new_path:
            print(f'Old path: {path}, New path: {new_path} exists')
            continue

        if path != new_path and not dry_run:
            path.rename(new_path)


if __name__ == '__main__':
    bad_words = ('Warhammer 40000',)
    rename_epubs('/Users/StimuL/Downloads/Кайафас Каин', bad_words)