# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import logging
import typing
from typing import Dict, List, NamedTuple, Optional
from uuid import UUID

from gi.repository import GObject
from pykeepass.attachment import Attachment
from pykeepass.entry import Entry
from pykeepass.group import Group

from passwordsafe.color_widget import Color
if typing.TYPE_CHECKING:
    from passwordsafe.database_manager import DatabaseManager


class Icon(NamedTuple):
    name: str
    visible: bool = False


# https://github.com/dlech/KeePass2.x/blob/4facf2f1ebc76eeddbe11975eccb0dc2b49dfc37/KeePassLib/PwEnums.cs#L81  # noqa: E501
# https://hsto.org/files/b1e/d20/e38/b1ed20e385d642cc870355fdef153fb9.png
# FIXME: Based on the names from the links above, some of the current
# icons should be replaced.
ICONS = {
    "0": Icon("dialog-password-symbolic", True),
    "1": Icon("network-wired-symbolic", True),
    "2": Icon("dialog-warning-symbolic"),
    "3": Icon("network-server-symbolic"),
    "4": Icon("document-edit-symbolic"),
    "5": Icon("media-view-subtitles-symbolic"),
    "6": Icon("application-x-addon-symbolic"),
    "7": Icon("accessories-text-editor-symbolic"),
    "8": Icon("network-wired-symbolic"),
    "9": Icon("mail-send-symbolic", True),
    "10": Icon("text-x-generic-symbolic"),
    "11": Icon("camera-photo-symbolic"),
    "12": Icon("network-wireless-signal-excellent-symbolic", True),
    "13": Icon("dialog-password-symbolic"),
    "14": Icon("colorimeter-colorhug-symbolic"),
    "15": Icon("scanner-symbolic"),
    "16": Icon("network-wired-symbolic"),
    "17": Icon("media-optical-cd-audio-symbolic"),
    "18": Icon("video-display-symbolic"),
    "19": Icon("mail-unread-symbolic", True),
    "20": Icon("emblem-system-symbolic"),
    "21": Icon("edit-paste-symbolic"),
    "22": Icon("edit-paste-symbolic"),
    "23": Icon("preferences-desktop-remote-desktop-symbolic", True),
    "24": Icon("uninterruptible-power-supply-symbolic"),
    "25": Icon("mail-unread-symbolic"),
    "26": Icon("media-floppy-symbolic"),
    "27": Icon("drive-harddisk-symbolic", True),
    "28": Icon("dialog-password-symbolic"),
    "29": Icon("dialog-password-symbolic"),
    "30": Icon("utilities-terminal-symbolic", True),
    "31": Icon("printer-symbolic"),
    "32": Icon("image-x-generic-symbolic"),
    "33": Icon("edit-select-all-symbolic"),
    "34": Icon("preferences-system-symbolic", True),
    "35": Icon("network-workgroup-symbolic"),
    "36": Icon("dialog-password-symbolic"),
    "37": Icon("dialog-password-symbolic"),
    "38": Icon("drive-harddisk-symbolic"),
    "39": Icon("document-open-recent-symbolic"),
    "40": Icon("system-search-symbolic"),
    "41": Icon("dialog-password-symbolic"),
    "42": Icon("media-flash-symbolic"),
    "43": Icon("user-trash-symbolic"),
    "44": Icon("accessories-text-editor-symbolic"),
    "45": Icon("edit-delete-symbolic"),
    "46": Icon("dialog-question-symbolic"),
    "47": Icon("package-x-generic-symbolic"),
    "48": Icon("folder-symbolic", True),
    "49": Icon("folder-open-symbolic"),
    "50": Icon("document-open-symbolic"),
    "51": Icon("system-lock-screen-symbolic"),
    "52": Icon("rotation-locked-symbolic"),
    "53": Icon("object-select-symbolic"),
    "54": Icon("document-edit-symbolic"),
    "55": Icon("image-x-generic-symbolic"),
    "56": Icon("accessories-dictionary-symbolic"),
    "57": Icon("view-list-symbolic"),
    "58": Icon("avatar-default-symbolic"),
    "59": Icon("applications-engineering-symbolic"),
    "60": Icon("go-home-symbolic"),
    "61": Icon("starred-symbolic"),
    "62": Icon("start-here-symbolic"),
    "63": Icon("dialog-password-symbolic"),
    "64": Icon("start-here-symbolic"),
    "65": Icon("accessories-dictionary-symbolic"),
    "66": Icon("dialog-password-symbolic"),
    "67": Icon("application-certificate-symbolic"),
    "68": Icon("phone-apple-iphone-symbolic")
}


class SafeEntry(GObject.GObject):
    # pylint: disable=too-few-public-methods
    # pylint: disable=too-many-instance-attributes

    _color_key = "color_prop_LcljUMJZ9X"
    _note_key = "Notes"

    def __init__(self, db_manager: DatabaseManager, entry: Entry) -> None:
        """GObject to handle a safe entry.

        :param DatabaseManager db_manager:  database of the entry
        :param Entry entry: entry to handle
        """
        super().__init__()

        self._db_manager: DatabaseManager = db_manager
        self._entry: Entry = entry

        self._attachments: List[Attachment] = entry.attachments or []

        self._attributes: Dict[str, str] = {
            key: value for key, value in entry.custom_properties.items()
            if key not in (self._color_key, self._note_key)}

        color_value: Color = entry.get_custom_property(self._color_key)
        self._color: str = color_value or Color.NONE.value

        self._icon_nr: str = entry.icon or ""
        self._name: str = entry.title or ""
        self._notes: str = entry.notes or ""
        self._password: str = entry.password or ""
        self._url: str = entry.url or ""
        self._username: str = entry.username or ""

    @property
    def entry(self) -> Entry:
        """Get entry

        :returns: entry
        :rtype: Entry
        """
        return self._entry

    @property
    def uuid(self) -> UUID:
        """UUID of the entry

        :returns: uuid of the entry
        :rtype: Group
        """
        return self._entry.uuid

    @property
    def parentgroup(self) -> Group:
        """Parent Group of the entry

        :returns: parent group
        :rtype: Group
        """
        return self._entry.parentgroup

    @GObject.Property(
        type=object, flags=GObject.ParamFlags.READABLE)
    def attachments(self) -> List[Attachment]:
        return self._attachments

    def add_attachment(self, byte_buffer: bytes, filename: str) -> Attachment:
        """Add an attachment to the entry

        :param bytes byte_buffer: attachment content
        :param str filename: attachment name
        :returns: attachment
        :rtype: Attachment
        """
        attachment_id = self._db_manager.db.add_binary(byte_buffer)
        attachment = self._entry.add_attachment(attachment_id, filename)
        self._attachments.append(attachment)
        self._db_manager.is_dirty = True

        return attachment

    def delete_attachment(self, attachment: Attachment) -> None:
        """Remove an attachment from the entry

        :param Attachmennt attachment: attachment to delete
        """
        self._db_manager.db.delete_binary(attachment.id)
        self._attachments.remove(attachment)
        self._db_manager.is_dirty = True

    def get_attachment(self, id_: str) -> Optional[Attachment]:
        """Get an attachment from its id.

        :param str id_: attachment id
        :returns: attachment
        :rtype: Attachment
        """
        for attachment in self._attachments:
            if str(attachment.id) == id_:
                return attachment

        return None

    def get_attachment_content(self, attachment: Attachment) -> bytes:
        """Get an attachment content

        :param Attachmennt attachment: attachment
        """
        return self._db_manager.db.binaries[attachment.id]

    @GObject.Property(
        type=object, flags=GObject.ParamFlags.READABLE)
    def attributes(self) -> Dict[str, str]:
        return self._attributes

    def has_attribute(self, key: str) -> bool:
        """Check if an attribute exists.

        :param str key: attribute key to check
        """
        return key in self._attributes

    def set_attribute(self, key: str, value: str) -> None:
        """Add or replace an entry attribute

        :param str key: attribute key
        :param str value: attribute value
        """
        self._entry.set_custom_property(key, value)
        self._attributes[key] = value
        self._db_manager.is_dirty = True
        self._db_manager.set_element_mtime(self._entry)

    def delete_attribute(self, key: str) -> None:
        """Delete an attribute

        :param key: attribute key to delete
        """
        if not self.has_attribute(key):
            return

        self._entry.delete_custom_property(key)
        self._attributes.pop(key)
        self._db_manager.is_dirty = True
        self._db_manager.set_element_mtime(self._entry)

    @GObject.Property(
        type=str, flags=GObject.ParamFlags.READWRITE)
    def color(self) -> str:
        """Get entry color

        :returns: color as string
        :rtype: str
        """
        return self._color

    @color.setter  # type: ignore
    def color(self, new_color: str) -> None:
        """Set an entry color

        :param str new_color: new color as string
        """
        if new_color != self._color:
            self._color = new_color
            self._entry.set_custom_property(self._color_key, new_color)
            self._db_manager.is_dirty = True
            self._db_manager.set_element_mtime(self._entry)

    @GObject.Property(type=object, flags=GObject.ParamFlags.READWRITE)
    def icon(self) -> Icon:
        """Get icon number

        :returns: icon number or "0" if no icon
        :rtype: str
        """
        try:
            return ICONS[self._icon_nr]
        except KeyError:
            logging.warning("Unknown icon %s", self._icon_nr)
            return ICONS["0"]

    @icon.setter  # type: ignore
    def icon(self, new_icon_nr: str) -> None:
        """Set icon number

        :param str new_icon_nr: new icon number
        """
        if new_icon_nr != self._icon_nr:
            self._icon_nr = new_icon_nr
            self._entry.icon = new_icon_nr
            self._db_manager.is_dirty = True
            self._db_manager.set_element_mtime(self._entry)
            self.notify("icon-name")

    @property
    def icon_handled(self) -> bool:
        try:
            icon = ICONS[self._icon_nr]
            return icon.visible
        except KeyError:
            logging.warning("Unknown icon %s", self._icon_nr)
            return False

    @GObject.Property(
        type=str, default="", flags=GObject.ParamFlags.READABLE)
    def icon_name(self) -> str:
        """Get the icon name

        :returns: icon name or the default icon if undefined
        :rtype: str
        """
        return self.props.icon.name

    @GObject.Property(
        type=str, default="", flags=GObject.ParamFlags.READWRITE)
    def name(self) -> str:
        """Get entry title

        :returns: title or an empty string if there is none
        :rtype: str
        """
        return self._name

    @name.setter  # type: ignore
    def name(self, new_name: str) -> None:
        """Set entry title

        :param str new_name: new title
        """
        if new_name != self._name:
            self._name = new_name
            self._entry.title = new_name
            self._db_manager.is_dirty = True
            self._db_manager.set_element_mtime(self._entry)

    @GObject.Property(
        type=str, default="", flags=GObject.ParamFlags.READWRITE)
    def notes(self) -> str:
        """Get entry notes

        :returns: notes or an empty string if there is none
        :rtype: str
        """
        return self._notes

    @notes.setter  # type: ignore
    def notes(self, new_notes: str) -> None:
        """Set entry notes

        :param str new_notes: new notes
        """
        if new_notes != self._notes:
            self._notes = new_notes
            self._entry.notes = new_notes
            self._db_manager.is_dirty = True
            self._db_manager.set_element_mtime(self._entry)

    @GObject.Property(
        type=str, default="", flags=GObject.ParamFlags.READWRITE)
    def password(self) -> str:
        """Get entry password

        :returns: password or an empty string if there is none
        :rtype: str
        """
        return self._password

    @password.setter  # type: ignore
    def password(self, new_password: str) -> None:
        """Set entry password

        :param str new_password: new password
        """
        if new_password != self._password:
            self._password = new_password
            self._entry.password = new_password
            self._db_manager.is_dirty = True
            self._db_manager.set_element_mtime(self._entry)

    @GObject.Property(
        type=str, default="", flags=GObject.ParamFlags.READWRITE)
    def url(self) -> str:
        """Get entry url

        :returns: url or an empty string if there is none
        :rtype: str
        """
        return self._url

    @url.setter  # type: ignore
    def url(self, new_url: str) -> None:
        """Set entry url

        :param str new_url: new url
        """
        if new_url != self._url:
            self._url = new_url
            self._entry.url = new_url
            self._db_manager.is_dirty = True
            self._db_manager.set_element_mtime(self._entry)

    @GObject.Property(
        type=str, default="", flags=GObject.ParamFlags.READWRITE)
    def username(self) -> str:
        """Get entry username

        :returns: username or an empty string if there is none
        :rtype: str
        """
        return self._username

    @username.setter  # type: ignore
    def username(self, new_username: str) -> None:
        """Set entry username

        :param str new_username: new username
        """
        if new_username != self._username:
            self._username = new_username
            self._entry.username = new_username
            self._db_manager.is_dirty = True
            self._db_manager.set_element_mtime(self._entry)
