## Calibre

[Calibre][calibre] используется для конвертации электронных книг в другие форматы.

1. Скачиваем и устанавливаем последнюю [версию][calibre_download]

2. Делаем симлинки для удобного доступа к командам (ebook-convert достаточно)

        ln -sf /Applications/calibre.app/Contents/MacOS/ebook-meta /usr/local/bin/ebook-meta
        ln -sf /Applications/calibre.app/Contents/MacOS/ebook-convert /usr/local/bin/ebook-convert
        ln -sf /Applications/calibre.app/Contents/MacOS/calibre-customize /usr/local/bin/calibre-customize

3. При необходимости устанавливаем плагины так (скорее всего не понадобится)

        calibre-customize -b ~/projects/selfpub/calibre-plugin/titles_and_notes


[calibre]: https://calibre-ebook.com/
[calibre_download]: https://download.calibre-ebook.com/


# Convert

1. Команда на конвертацию

         ebook-convert-helper -i fb2 -o epub -r --dir {dir_path} --delete


# Change name from translit

1. Идем в `epub/rename_epubs.py`
2. Прописываем путь к папке (проход по папкам рекурсивный)
3. При необходимости прописываем слова исключения, которые нужно убрать из названия
4. Запускаем