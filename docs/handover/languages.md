# Languages

The app speaks English, Arabic, German, Spanish and French. The user picks one in
Settings → Language, and it changes every page straight away. On a first run the
computer's own language is used if it is one of the five, otherwise English.

## How it works

- `app/i18n/__init__.py` has `t()`. English is written in the code and is also
  the key: `locales/de.json` maps each English string to its German.
- Missing translations fall back to English, and a translation whose `{fields}`
  do not match the English is ignored, so a mistake can never crash the app.
- **Translation happens where text is shown.** The shared widgets pass whatever
  they are given through `t()`: `heading`, `muted`, `hint`, every button,
  `checkbox`, `line_edit` and `text_box` placeholders, `Section`, `FormRow`,
  `StatTile`, `StatusRow`, `TabBar`, `ChoiceButtons`, `MenuButton`, `DataTable`,
  `ConfirmDialog`, `ChoiceDialog`, `InfoDialog`, toasts (`notify`), table headers
  and the sidebar. So a plain English string can be handed to them unchanged.
- **Sentences with a value** are templates: `t("{count} contacts imported",
  count=n)`. The template is the key, and each language puts the number where its
  grammar wants it. A value that is itself app wording (a status, a category) is
  translated too.
- **Text set straight on a Qt widget** (`setText`, `setToolTip`,
  `setPlaceholderText`, `QLabel(...)`, `QAction(...)`, file dialog titles and
  filters) is wrapped in `t(...)` at the call.
- **Nothing is translated at import time.** Module-level lists such as
  `PAGE_HELP_SECTIONS` stay English and are translated when shown. That is what
  lets the language change while the app is open: `MainWindow.change_language()`
  rebuilds the window, the same way a text size change does.
- **Drop-downs** (`combo()`) show translated choices but `currentText()` returns
  the English, so page code compares and saves English. For data (sheet names,
  column headings, times) pass `translate=False`; for data with one app choice in
  it, `translate={"(none)"}`.
- **Tabs** keep their English name as the key (`tabs.set("Preview & score")`);
  only the button is translated.

## Right to left (Arabic)

- `run.py` and `change_language()` set the application's layout direction, and
  Qt mirrors every layout. Two hand-made pieces handle it themselves:
  `FlowLayout` mirrors its rows, and the delay slider stays left to right on
  purpose (like a ruler).
- Toasts appear bottom-left instead of bottom-right.
- An email whose message is mostly Arabic is sent with `dir="rtl"`
  (`composer.is_right_to_left`).

## What the language also changes in emails

- The unsubscribe line (`composer.unsubscribe_footer`). Its reply word
  (Abmelden, Baja, Désabonner, إلغاء الاشتراك) is in
  `imap_sync.UNSUBSCRIBE_PHRASES`, so replies are caught in every language.
- What `{{FirstName}}` and `{{Company}}` become when a contact has none
  (`merge.FALLBACKS`).
- The "Show me an example" subjects and messages (`app/core/examples.py`), and
  the headings of the blank spreadsheet. The importer recognises subject /
  message / signature headings in all five languages.
- The spam score checks trigger and sales words in all five languages whatever
  the app's language, because an email may be written in another.

## Adding or changing text

1. Write the English in the code: through a shared widget, or `t("...")`, or
   `t("... {name} ...", name=value)` for a sentence with a value.
2. `python tools/i18n.py missing ar` prints a numbered list of what Arabic lacks.
   Do the same for de, es and fr.
3. Write the translations to a file, one per line, `NUMBER<TAB>translation`,
   with line breaks inside a translation written as `\n`.
4. `python tools/i18n.py merge ar FILE` (and the others).
5. `python tools/i18n.py check` must say every language is complete, and
   `python -m pytest tests/test_i18n.py` must pass.

Changing existing English text makes it a new key: the old translation stops
matching and the new one shows up as missing. Keep the `{fields}` identical in
every translation, keep leading and trailing spaces, and never use em dashes, en
dashes or typographic ellipses (the test scans the JSON files too).

`tools/i18n.py` finds text by reading the source: the first argument of every
`t(...)`, plus plain English strings in the UI and user-facing core modules. If
it picks up something that is not wording (a file name, a code), add it to
`IGNORE` or `SKIP_NAMES` in that file.

## Translation glossary

Keep page names consistent with the sidebar when a sentence mentions them.

| English | ar | de | es | fr |
|---|---|---|---|---|
| My message | رسالتي | Meine Nachricht | Mi mensaje | Mon message |
| My contacts | جهات الاتصال | Meine Kontakte | Mis contactos | Mes contacts |
| Domain check | فحص النطاق | Domain-Prüfung | Revisión del dominio | Vérification du domaine |
| Sending options | خيارات الإرسال | Versandoptionen | Opciones de envío | Options d'envoi |
| My email account | حساب بريدي | Mein E-Mail-Konto | Mi cuenta de correo | Mon compte e-mail |
| Preview & score | المعاينة والتقييم | Vorschau & Bewertung | Vista previa y puntuación | Aperçu et score |
| Promotions tab | تبويب العروض الترويجية | Tab Werbung | Pestaña Promociones | Onglet Promotions |
| Unsubscribe | إلغاء الاشتراك | Abmelden | Baja | Désabonner |

German uses "Sie", French "vous", Spanish "tú".
