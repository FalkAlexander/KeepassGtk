# SPDX-License-Identifier: GPL-3.0-only
"""Gtk.Button representing a path element in the pathbar"""
from typing import Union

from gi.repository import Gtk
from pykeepass.group import Group

from passwordsafe.safe_entry import SafeEntry


class PathbarButton(Gtk.Button):
    """Gtk.Button representing a path element in the pathbar

    notable instance variables are:
    .uuid: the UUID of the group or entry
    """

    def __init__(self, element: Union[SafeEntry, Group]):
        Gtk.Button.__init__(self)
        self.set_name("PathbarButtonDynamic")

        self._is_group = isinstance(element, Group)
        self._element: Union[SafeEntry, Group] = element

    @property
    def is_group(self) -> bool:
        return self._is_group

    @property
    def element(self) -> Union[SafeEntry, Group]:
        return self._element
