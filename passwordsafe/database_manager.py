# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import logging
from datetime import datetime
from gettext import gettext as _
from typing import Optional, Union
from uuid import UUID

from gi.repository import Gio, GObject
from pykeepass import PyKeePass
from pykeepass.entry import Entry
from pykeepass.group import Group

from passwordsafe.safe_element import SafeElement, SafeEntry, SafeGroup
from passwordsafe.utils import format_time


class DatabaseManager(GObject.GObject):
    # pylint: disable=too-many-public-methods

    """Implements database functionality that is independent of the UI

    Useful attributes:
     .database_path: str containing the filepath of the database

    Group objects are of type `pykeepass.group.Group`
    Entry objects are of type `pykeepass.entry.Entry`
    Instances of both have useful attributes:
    .uuid: a `uuid.UUID` object
    """

    # self.db contains a `PyKeePass` database
    password_try = ""
    keyfile_hash = NotImplemented
    _is_dirty = False  # Does the database need saving?
    save_running = False

    locked = GObject.Property(
        type=bool, default=False, flags=GObject.ParamFlags.READWRITE)

    def __init__(
        self,
        database_path: str,
        password: Optional[str] = None,
        keyfile: Optional[str] = None,
    ) -> None:
        super().__init__()

        # password remains accessible as self.db.password
        self.db = PyKeePass(database_path, password, keyfile)  # pylint: disable=C0103
        self.database_path = database_path

    #
    # Database Modifications
    #

    # Add new group to database
    def add_group_to_database(self, name, icon, notes, parent_group):
        new_location = parent_group.uuid
        group = self.db.add_group(parent_group, name, icon=icon, notes=notes)
        self.set_element_mtime(parent_group)
        safe_group = SafeGroup(self, group)
        self.emit("element-added", safe_group, new_location)

        return safe_group

    # Add new entry to database
    def add_entry_to_database(
        self,
        group: Group,
        name: Optional[str] = "",
        username: Optional[str] = "",
        password: Optional[str] = "",
    ) -> SafeEntry:
        force: bool = self.check_entry_in_group_exists("", group)
        entry = self.db.add_entry(
            group,
            name,
            username,
            password,
            url=None,
            notes=None,
            expiry_time=None,
            tags=None,
            icon="0",
            force_creation=force,
        )
        self.set_element_mtime(group)
        safe_entry = SafeEntry(self, entry)
        self.emit("element-added", safe_entry, safe_entry.parentgroup.uuid)

        return safe_entry

    # Delete an entry
    def delete_from_database(self, entity: Union[Entry, Group]) -> None:
        """Delete an Entry or a Group from the database.

        :param entity: Entity or Group to delete
        """
        if isinstance(entity, Entry):
            self.db.delete_entry(entity)
        else:
            self.db.delete_group(entity)

        self.emit("element-removed", entity.uuid)
        if entity.parentgroup is not None:
            self.set_element_mtime(entity.parentgroup)

    def duplicate_entry(self, entry: Entry) -> None:
        """Duplicate an entry

        :param Entry entry: entry to duplicate
        """
        title: str = entry.title or ""
        username: str = entry.username or ""
        password: str = entry.password or ""

        # NOTE: With clone is meant a duplicated object, not the process
        # of cloning/duplication; "the" clone
        clone_entry: Entry = self.db.add_entry(
            entry.parentgroup, title + " - " + _("Clone"), username, password,
            url=entry.url, notes=entry.notes, expiry_time=entry.expiry_time,
            tags=entry.tags, icon=entry.icon, force_creation=True)

        # Add custom properties
        for key in entry.custom_properties:
            value: str = entry.custom_properties[key] or ""
            clone_entry.set_custom_property(key, value)

        safe_entry = SafeEntry(self, clone_entry)
        self.emit("element-added", safe_entry, safe_entry.parentgroup.uuid)
        if entry.parentgroup is not None:
            self.set_element_mtime(entry.parentgroup)

    # Write all changes to database
    def save_database(self, notification=False):
        if self.save_running is False and self.is_dirty:
            self.save_running = True

            # TODO This could be simplified a lot
            # if a copy of the keyfile was stored in memory.
            # This would require careful checks for functionality that
            # modifies the keyfile.
            if self.db.keyfile:
                gfile = Gio.File.new_for_path(self.db.keyfile)
                exists = gfile.query_exists()
                if not exists:
                    self.save_running = False
                    logging.error("Could not find keyfile")
                    if notification:
                        self.emit("save-notification", False)

                    return

            try:
                self.db.save()
                logging.debug("Saved database")
                self.is_dirty = False
            except Exception:  # pylint: disable=broad-except
                logging.error("Error occurred while saving database")

            if notification:
                self.emit("save-notification", not self.is_dirty)

            self.save_running = False

    @property
    def password(self) -> str:
        """Get the current password or '' if not set"""
        return self.db.password or ""

    @password.setter
    def password(self, new_password: Optional[str]) -> None:
        """Set database password (None if a keyfile is used)"""
        self.db.password = new_password
        self.is_dirty = True

    # Set database keyfile
    def set_database_keyfile(self, new_keyfile):
        self.db.keyfile = new_keyfile
        self.is_dirty = True

    #
    # Entry Modifications
    #

    # Move an entry to another group
    def move_entry(self, uuid, destination_group_object):
        entry = self.db.find_entries(uuid=uuid, first=True)
        old_location = entry.parentgroup.uuid
        new_location = destination_group_object.uuid

        if old_location == new_location:
            return

        # TODO: we will crash if uuid does not exist
        self.db.move_entry(entry, destination_group_object)
        # pylint: disable=no-member
        if entry.parentgroup:
            self.set_element_mtime(entry.parentgroup)
        self.set_element_mtime(destination_group_object)

        safe_entry = SafeEntry(self, entry)

        self.emit("element-moved", safe_entry, old_location, new_location)

    def set_element_atime(self, element):
        element.atime = datetime.now()

    def set_element_mtime(self, element):
        element.mtime = datetime.now()

    # Move an group
    def move_group(self, group: Group, dest_group: Group) -> None:
        old_location = group.parentgroup.uuid
        new_location = dest_group.uuid

        if old_location == new_location:
            return

        self.db.move_group(group, dest_group)
        if group.parentgroup is not None:
            self.set_element_mtime(group.parentgroup)
        self.set_element_mtime(dest_group)

        safe_group = SafeGroup(self, group)
        self.emit("element-moved", safe_group, old_location, new_location)

    #
    # Read Database
    #

    # Check if entry with title in group exists
    def check_entry_in_group_exists(self, title, group):
        entry = self.db.find_entries(title=title, group=group, recursive=False, history=False, first=True)
        if entry is None:
            return False
        return True

    #
    # Properties
    #

    def get_element_creation_date(self, element: SafeElement) -> str:
        """Returns a string of the Entry|Groups creation time or ''"""
        elem = element.element
        return format_time(elem.ctime)

    def get_element_acessed_date(self, element: SafeElement) -> str:
        """Returns a string of the Entry|Groups access time or ''"""
        elem = element.element
        return format_time(elem.atime)

    def get_element_modified_date(self, element: SafeElement) -> str:
        """Returns a string of the Entry|Groups modification time or ''"""
        elem = element.element
        return format_time(elem.mtime)

    #
    # Database creation methods
    #

    # Set the first password entered by the user (for comparing reasons)
    def set_password_try(self, password):
        self.password_try = password

    def compare_passwords(self, password2: str) -> bool:
        """Compare the first password entered by the user with the second one

        It also does not allow empty passwords.
        :returns: True if passwords match and are non-empty.
        """
        if password2 and self.password_try == password2:
            return True
        return False

    def create_keyfile_hash(self, keyfile_path):
        """Create keyfile hash and returns it"""
        hasher = hashlib.sha512()
        with open(keyfile_path, 'rb') as file:
            buffer = 0
            while buffer != b'':
                buffer = file.read(1024)
                hasher.update(buffer)
        return hasher.hexdigest()

    # Set keyfile hash
    def set_keyfile_hash(self, keyfile_path):
        self.keyfile_hash = self.create_keyfile_hash(keyfile_path)

    def parent_checker(self, current_group, moved_group):
        """Returns True if moved_group is an ancestor of current_group"""
        # recursively invoke ourself until we reach the root group
        if current_group.is_root_group:
            return False
        if current_group.uuid == moved_group.uuid:
            return True
        return self.parent_checker(current_group.parentgroup, moved_group)

    @property
    def version(self):
        """returns the database version"""
        return self.db.version

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    @is_dirty.setter
    def is_dirty(self, value: bool) -> None:
        """
        Enables the save_dirty action whenever the Safe is in a
        dirty state. This makes the save menu button sensitive.
        """
        app = Gio.Application.get_default()
        save_action = app.lookup_action("db.save_dirty")
        save_action.set_enabled(value)
        self._is_dirty = value

    @GObject.Signal(arg_types=(bool,))
    def save_notification(self, _saved):
        return

    @GObject.Signal(arg_types=(SafeElement, object,))
    def element_added(self, _element: SafeElement, _parent_uuid: UUID) -> None:
        """Signal emitted when a new element was added to the database
        it carries the UUID in string format of the parent group to which
        the entrie was added."""
        self.is_dirty = True
        logging.debug("Added new element to safe")

    @GObject.Signal(arg_types=(object,))
    def element_removed(self, element_uuid: UUID) -> None:
        self.is_dirty = True
        logging.debug("Element %s removed from safe", element_uuid)

    @GObject.Signal(arg_types=(SafeElement, object, object))
    def element_moved(
        self, _moved_element: SafeElement, _old_location_uuid: UUID, _new_location_uuid: UUID
    ) -> None:
        self.is_dirty = True
        logging.debug("Element moved safe")
