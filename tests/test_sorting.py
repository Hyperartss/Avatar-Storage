"""Tests for sorting and for the filter state surviving a refresh.

    QT_QPA_PLATFORM=offscreen python3 tests/test_sorting.py
"""

import os
import shutil
import hashlib
import sys
import tempfile
from pathlib import Path
from PyQt6.QtCore import Qt

REAL_APP_DIR = Path(__file__).resolve().parent.parent

EXCLUDE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".venv", "venv", ".git",
    "*.db", "*.db-wal", "*.db-shm", "session.json", "cache",
)

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  pass  {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


def data_snapshot(directory):
    snapshot = {}
    for name in ("session.json", "avatar_library.db"):
        path = directory / name
        snapshot[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    cache = directory / "cache"
    snapshot["cache"] = sorted(p.name for p in cache.iterdir()) if cache.is_dir() else None
    return snapshot


def payload(n, name, author, added, **extra):
    data = {
        "id": f"avtr_0000000{n}-0000-0000-0000-000000000000",
        "name": name,
        "author": author,
        "author_id": f"usr_00000000-0000-0000-0000-00000000000{n}",
        "thumbnail_url": "",
        "description": "",
        "tags": [],
        "release_status": "public",
        "version": "1",
        "unity_version": "2022",
        "date_published": 0,
        "date_updated": 0,
        "downloads": 0,
        "favorites_count": 0,
        "rating": 0.0,
        "is_public": True,
        "url": "",
    }
    data.update(extra)
    db_update = added
    return data, db_update


def names(rows):
    return [r["name"] for r in rows]


def sidebar_item_text(list_widget, category_id):
    """Return the visible text of the sidebar item for `category_id`."""
    for i in range(list_widget.count()):
        item = list_widget.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == category_id:
            return item.text()
    return ""


def main():
    root = Path(tempfile.mkdtemp(prefix="infavis-sort-"))
    app = root / "app"
    shutil.copytree(REAL_APP_DIR, app, ignore=EXCLUDE)
    sys.path.insert(0, str(app))

    repo_before = data_snapshot(REAL_APP_DIR)

    os.environ["HOME"] = str(root / "home")
    os.environ["INF_AVIS_DATA_DIR"] = str(root / "data")
    os.environ["INF_AVIS_CONFIG_DIR"] = str(root / "config")
    os.environ["INF_AVIS_CACHE_DIR"] = str(root / "cache")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QEventLoop, QTimer, Qt
    import database as db
    from gui.main_window import MainWindow

    qt = QApplication(sys.argv)
    db.init_db()

    rows = [
        payload(1, "Charlie", "Zoe", 100, favorites_count=5, downloads=10,
                rating=3.0, date_updated=500),
        payload(2, "alpha", "Yan", 300, favorites_count=50, downloads=1,
                rating=5.0, date_updated=100),
        payload(3, "Bravo", "Xu", 200, favorites_count=20, downloads=99,
                rating=4.0, date_updated=900),
    ]
    for data, _ in rows:
        db.upsert_avatar(data)
    # date_added comes from the insert, so set it explicitly for a stable order.
    conn = db.get_connection()
    for index, (data, _) in enumerate(rows):
        conn.execute("UPDATE avatars SET date_added = ? WHERE avatar_id = ?",
                     (100 + index * 100, data["id"]))
    conn.commit()
    conn.close()

    print("sorting")
    check("name ascending is case-insensitive",
          names(db.get_all_avatars(sort_by="name", sort_dir="ASC")) ==
          ["alpha", "Bravo", "Charlie"],
          str(names(db.get_all_avatars(sort_by="name", sort_dir="ASC"))))
    check("name descending",
          names(db.get_all_avatars(sort_by="name", sort_dir="DESC")) ==
          ["Charlie", "Bravo", "alpha"])
    check("author ascending",
          names(db.get_all_avatars(sort_by="author", sort_dir="ASC")) ==
          ["Bravo", "alpha", "Charlie"],
          str(names(db.get_all_avatars(sort_by="author", sort_dir="ASC"))))
    check("most favourited",
          names(db.get_all_avatars(sort_by="favorites_count", sort_dir="DESC")) ==
          ["alpha", "Bravo", "Charlie"])
    check("most downloaded",
          names(db.get_all_avatars(sort_by="downloads", sort_dir="DESC")) ==
          ["Bravo", "Charlie", "alpha"])
    check("highest rated",
          names(db.get_all_avatars(sort_by="rating", sort_dir="DESC")) ==
          ["alpha", "Bravo", "Charlie"])
    check("recently updated on VRChat",
          names(db.get_all_avatars(sort_by="date_updated", sort_dir="DESC")) ==
          ["Bravo", "Charlie", "alpha"])
    check("newest added first",
          names(db.get_all_avatars(sort_by="date_added", sort_dir="DESC")) ==
          ["Bravo", "alpha", "Charlie"],
          str(names(db.get_all_avatars(sort_by="date_added", sort_dir="DESC"))))
    check("oldest added first",
          names(db.get_all_avatars(sort_by="date_added", sort_dir="ASC")) ==
          ["Charlie", "alpha", "Bravo"])

    print("sorting is safe and combined with filters")
    check("unknown sort column falls back to date_added",
          len(db.get_all_avatars(sort_by="; DROP TABLE avatars")) == 3)
    check("hostile direction falls back to DESC",
          names(db.get_all_avatars(sort_by="name",
                                   sort_dir="ASC; DELETE FROM avatars")) ==
          ["Charlie", "Bravo", "alpha"],
          str(names(db.get_all_avatars(sort_by="name",
                                       sort_dir="ASC; DELETE FROM avatars"))))
    check("table survived the injection attempt",
          len(db.get_all_avatars()) == 3)
    check("sorting works with a search filter",
          names(db.get_all_avatars(search="a", sort_by="name", sort_dir="ASC")) != [])
    cat = db.create_category("Sorted")
    db.add_avatar_to_category(rows[0][0]["id"], cat)
    check("sorting works inside a category",
          names(db.get_all_avatars(category_id=cat, sort_by="name", sort_dir="ASC")) ==
          ["Charlie"])

    print("stable secondary ordering")
    check("equal keys fall back to name",
          [r["name"] for r in db.get_all_avatars(sort_by="release_status",
                                                 sort_dir="DESC")] ==
          ["alpha", "Bravo", "Charlie"])

    print("window wiring")
    window = MainWindow()
    window.show()
    qt.processEvents()

    options = [window.sort_combo.itemData(i)
               for i in range(window.sort_combo.count())]
    check("sort combo populated", len(options) >= 8, str(options))
    check("sort combo has name both ways",
          "name" in options and "name_desc" in options)

    window.sort_combo.setCurrentIndex(options.index("name"))
    check("name sort resolves to ASC",
          window.current_sort() == ("name", "ASC"), str(window.current_sort()))
    window.sort_combo.setCurrentIndex(options.index("name_desc"))
    check("name_desc resolves to DESC",
          window.current_sort() == ("name", "DESC"), str(window.current_sort()))
    window.sort_combo.setCurrentIndex(options.index("date_added_oldest"))
    check("oldest first resolves to ASC",
          window.current_sort() == ("date_added", "ASC"), str(window.current_sort()))

    print("filter state survives a refresh")
    window.sort_combo.setCurrentIndex(options.index("name"))
    window.search_input.setText("a")
    qt.processEvents()
    window.current_category_id = None

    before = window.avatar_list.current_search
    window.avatar_list.toggle_favorite(rows[1][0]["id"])
    qt.processEvents()
    check("search preserved after a favourite toggle",
          window.avatar_list.current_search == before == "a",
          f"{before!r} -> {window.avatar_list.current_search!r}")
    check("sort preserved after a favourite toggle",
          window.avatar_list.current_sort_by == "name",
          str(window.avatar_list.current_sort_by))

    window.search_input.setText("")
    qt.processEvents()
    cat2 = db.create_category("Only Charlie")
    db.add_avatar_to_category(rows[0][0]["id"], cat2)
    window.load_categories()
    window.current_category_id = cat2
    window.load_avatars()
    qt.processEvents()
    check("category applied",
          window.avatar_list.current_category_id == cat2,
          str(window.avatar_list.current_category_id))
    window.avatar_list.toggle_favorite(rows[0][0]["id"])
    qt.processEvents()
    check("category preserved after a favourite toggle",
          window.avatar_list.current_category_id == cat2,
          str(window.avatar_list.current_category_id))
    check("sort still applied inside the category",
          window.avatar_list.current_sort_by == "name",
          str(window.avatar_list.current_sort_by))

    print("resize does not reload")
    window.avatar_list.current_search = "zzz-sentinel"
    loaders = window.avatar_list.thumbnail_loaders
    window.resize(1000, 700)
    qt.processEvents()
    window.resize(1400, 900)
    qt.processEvents()
    check("search survives a resize",
          window.avatar_list.current_search == "zzz-sentinel",
          str(window.avatar_list.current_search))
    check("cards were not rebuilt on resize",
          window.avatar_list.thumbnail_loaders is loaders)
    check("grid still populated", window.avatar_list.grid.count() > 0)

    print("transferring between categories")
    # set_avatar_categories replaces membership rather than appending, which
    # is what makes it a transfer.
    all_cats = {c["name"]: c["id"] for c in db.get_all_categories()}
    check("the suite has categories to work with", len(all_cats) >= 2,
          str(sorted(all_cats)))
    subject = rows[0][0]["id"]
    first, second = list(all_cats.values())[:2]

    check("save into one category",
          db.set_avatar_categories(subject, [first]))
    check("it is in exactly that one",
          [r["id"] for r in db.get_avatar_categories(subject)] == [first],
          str([r["name"] for r in db.get_avatar_categories(subject)]))

    check("transfer to another replaces, not appends",
          db.set_avatar_categories(subject, [second]))
    check("the old category was dropped",
          [r["id"] for r in db.get_avatar_categories(subject)] == [second],
          str([r["name"] for r in db.get_avatar_categories(subject)]))

    db.set_avatar_categories(subject, [first, second])
    check("an avatar can be in several at once",
          sorted(r["id"] for r in db.get_avatar_categories(subject))
          == sorted([first, second]))

    check("unticking everything clears it",
          db.set_avatar_categories(subject, []))
    check("nothing is left", db.get_avatar_categories(subject) == [],
          str(db.get_avatar_categories(subject)))

    check("duplicates collapse",
          db.set_avatar_categories(subject, [first, first, first]))
    check("stored once",
          len(db.get_avatar_categories(subject)) == 1,
          str(db.get_avatar_categories(subject)))

    # A category deleted elsewhere must not break a save; it is dropped.
    ghost = max(r["id"] for r in db.get_all_categories()) + 5000
    check("an unknown category id does not raise",
          db.set_avatar_categories(subject, [first, ghost, "junk", None]))
    check("the unknown id was ignored",
          [r["id"] for r in db.get_avatar_categories(subject)] == [first],
          str(db.get_avatar_categories(subject)))

    other = rows[1][0]["id"]
    check("one avatar's categories are not another's",
          db.set_avatar_categories(subject, [first]) and
          db.set_avatar_categories(other, [second]))
    check("first is only in its own", [r["id"] for r in
          db.get_avatar_categories(subject)] == [first])
    check("second is only in its own", [r["id"] for r in
          db.get_avatar_categories(other)] == [second])

    print("the folder button opens the category picker")
    from PyQt6.QtWidgets import QDialog
    from gui.category_picker import CategoryPickerDialog

    window.avatar_list.load_avatars()
    qt.processEvents()
    card = None
    for index in range(window.avatar_list.grid.count()):
        widget = window.avatar_list.grid.itemAt(index).widget()
        if widget is not None:
            card = widget
            break
    check("there is a card to click", card is not None)
    check("the card has a star button", hasattr(card, "fav_btn"))
    check("the card has a folder button", hasattr(card, "move_btn"))

    opened = {}
    real_exec = QDialog.exec

    def reject_immediately(dialog):
        opened["dialog"] = dialog
        return QDialog.DialogCode.Rejected

    was_favorite = bool(db.get_avatar(card.avatar_id)["favorite"])
    before_categories = [r["id"] for r in db.get_avatar_categories(card.avatar_id)]
    QDialog.exec = reject_immediately
    card.move_btn.click()
    QDialog.exec = real_exec
    check("clicking the folder opens the picker",
          isinstance(opened.get("dialog"), CategoryPickerDialog),
          str(type(opened.get("dialog"))))
    check("it knows which avatar it is for",
          opened["dialog"].avatar_id == card.avatar_id)
    check("cancelling leaves the favourite flag alone",
          bool(db.get_avatar(card.avatar_id)["favorite"]) == was_favorite)
    check("cancelling leaves the categories alone",
          [r["id"] for r in db.get_avatar_categories(card.avatar_id)]
          == before_categories,
          str(db.get_avatar_categories(card.avatar_id)))

    print("the picker preselects what is already set")
    db.set_avatar_categories(card.avatar_id, [first])
    dialog = CategoryPickerDialog(None, card.avatar_id, card.avatar_data["name"])
    preselected = dialog.selected_category_ids()
    check("the avatar's current category is ticked",
          first in preselected, str(preselected))
    check("others are not ticked",
          second not in preselected, str(preselected))
    check("one box per category",
          len(dialog.boxes) == len(db.get_all_categories()),
          f"{len(dialog.boxes)} vs {len(db.get_all_categories())}")

    print("saving from the picker writes the ticked set")
    for box in dialog.boxes:
        box.setChecked(box.category_id == second)
    dialog.on_save()
    check("it moved to the ticked category",
          [r["id"] for r in db.get_avatar_categories(card.avatar_id)] == [second],
          str([r["name"] for r in db.get_avatar_categories(card.avatar_id)]))

    print("the picker can make a category inline")
    dialog = CategoryPickerDialog(None, card.avatar_id, card.avatar_data["name"])
    before_count = len(dialog.boxes)
    dialog.new_name.setText("Made In The Picker")
    dialog.add_category()
    check("a box was added", len(dialog.boxes) == before_count + 1,
          f"{before_count} -> {len(dialog.boxes)}")
    check("it was created in the database",
          any(c["name"] == "Made In The Picker"
              for c in db.get_all_categories()))
    check("it is ticked ready to use",
          dialog.selected_category_ids() and "Made In The Picker" in
          [b.text().split("  (")[0] for b in dialog.boxes if b.isChecked()],
          str([b.text() for b in dialog.boxes if b.isChecked()]))
    dialog.on_save()
    check("and the avatar lands in it",
          any(r["name"] == "Made In The Picker"
              for r in db.get_avatar_categories(card.avatar_id)),
          str([r["name"] for r in db.get_avatar_categories(card.avatar_id)]))

    dialog = CategoryPickerDialog(None, card.avatar_id, "")
    dialog.new_name.setText("made in the picker")
    dialog.add_category()
    check("a duplicate name is refused", len(dialog.boxes) ==
          len(db.get_all_categories()), str(len(dialog.boxes)))
    check("and it says so", "already exists" in dialog.notice.text(),
          dialog.notice.text())

    print("the picker honours the favourite checkbox")
    dialog = CategoryPickerDialog(None, card.avatar_id, card.avatar_data["name"])
    check("it starts from the stored flag",
          dialog.fav_box.isChecked() == bool(
              db.get_avatar(card.avatar_id)["favorite"]))
    dialog.fav_box.setChecked(not dialog.fav_box.isChecked())
    dialog.on_save()
    check("the flag flipped",
          bool(db.get_avatar(card.avatar_id)["favorite"]) != was_favorite)
    check("the categories survived the flag change",
          bool(db.get_avatar_categories(card.avatar_id)),
          str(db.get_avatar_categories(card.avatar_id)))

    print("the picker survives the filter it just changed")
    db.set_avatar_categories(card.avatar_id, [first])
    window.current_category_id = first
    window.load_avatars()
    qt.processEvents()
    check("the avatar shows under that category",
          any(a["avatar_id"] == card.avatar_id
              for a in window.avatar_list.avatars),
          str(len(window.avatar_list.avatars)))

    def untick_everything(dialog):
        for box in dialog.boxes:
            box.setChecked(False)
        dialog.on_save()
        return QDialog.DialogCode.Accepted

    QDialog.exec = untick_everything
    window.avatar_list.on_edit_categories(card.avatar_data)
    QDialog.exec = real_exec
    check("it is gone from the filtered list",
          not any(a["avatar_id"] == card.avatar_id
                  for a in window.avatar_list.avatars),
          str(len(window.avatar_list.avatars)))
    check("and out of the category", db.get_avatar_categories(card.avatar_id) == [],
          str(db.get_avatar_categories(card.avatar_id)))
    # Other avatars may still be filed here, so compare against the real count
    # rather than assuming zero.
    check("the sidebar count was rebuilt",
          sidebar_item_text(window.sidebar.list, first) ==
          f"{[c['name'] for c in db.get_all_categories() if c['id'] == first][0]} "
          f"({db.get_category_avatar_count(first)})")

    window.close()
    qt.processEvents()

    print("repository untouched")
    repo_after = data_snapshot(REAL_APP_DIR)
    for name in repo_before:
        check(f"repo {name} unchanged", repo_before[name] == repo_after[name],
              f"{repo_before[name]!r} -> {repo_after[name]!r}")

    shutil.rmtree(root, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())