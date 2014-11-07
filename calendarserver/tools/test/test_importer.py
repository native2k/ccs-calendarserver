##
# Copyright (c) 2014 Apple Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
##

"""
Unit tests for L{calendarsever.tools.importer}.
"""

from calendarserver.tools.importer import importCollectionComponent, ImportException
from twext.enterprise.jobqueue import JobItem
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twistedcaldav import customxml
from twistedcaldav.ical import Component
from twistedcaldav.test.util import StoreTestCase
from txdav.base.propertystore.base import PropertyName
from txdav.xml import element as davxml


DATA_MISSING_SOURCE = """BEGIN:VCALENDAR
CALSCALE:GREGORIAN
PRODID:-//Apple Computer\, Inc//iCal 2.0//EN
VERSION:2.0
END:VCALENDAR
"""

DATA_NO_SCHEDULING = """BEGIN:VCALENDAR
VERSION:2.0
NAME:Sample Import Calendar
COLOR:#0E61B9FF
SOURCE;VALUE=URI:http://example.com/calendars/__uids__/user01/calendar/
PRODID:-//CALENDARSERVER.ORG//NONSGML Version 1//EN
BEGIN:VEVENT
UID:5CE3B280-DBC9-4E8E-B0B2-996754020E5F
DTSTART;TZID=America/Los_Angeles:20141108T093000
DTEND;TZID=America/Los_Angeles:20141108T103000
CREATED:20141106T192546Z
DTSTAMP:20141106T192546Z
RRULE:FREQ=DAILY
SEQUENCE:0
SUMMARY:repeating event
TRANSP:OPAQUE
END:VEVENT
BEGIN:VEVENT
UID:5CE3B280-DBC9-4E8E-B0B2-996754020E5F
RECURRENCE-ID;TZID=America/Los_Angeles:20141111T093000
DTSTART;TZID=America/Los_Angeles:20141111T110000
DTEND;TZID=America/Los_Angeles:20141111T120000
CREATED:20141106T192546Z
DTSTAMP:20141106T192546Z
SEQUENCE:0
SUMMARY:repeating event
TRANSP:OPAQUE
END:VEVENT
BEGIN:VEVENT
UID:F6342D53-7D5E-4B5E-9E0A-F0A08977AFE5
DTSTART;TZID=America/Los_Angeles:20141108T080000
DTEND;TZID=America/Los_Angeles:20141108T091500
CREATED:20141104T205338Z
DTSTAMP:20141104T205338Z
SEQUENCE:0
SUMMARY:simple event
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
"""

DATA_NO_SCHEDULING_REIMPORT = """BEGIN:VCALENDAR
VERSION:2.0
NAME:Sample Import Calendar Reimported
COLOR:#FFFFFFFF
SOURCE;VALUE=URI:http://example.com/calendars/__uids__/user01/calendar/
PRODID:-//CALENDARSERVER.ORG//NONSGML Version 1//EN
BEGIN:VEVENT
UID:5CE3B280-DBC9-4E8E-B0B2-996754020E5F
DTSTART;TZID=America/Los_Angeles:20141108T093000
DTEND;TZID=America/Los_Angeles:20141108T103000
CREATED:20141106T192546Z
DTSTAMP:20141106T192546Z
RRULE:FREQ=DAILY
SEQUENCE:0
SUMMARY:repeating event
TRANSP:OPAQUE
END:VEVENT
BEGIN:VEVENT
UID:5CE3B280-DBC9-4E8E-B0B2-996754020E5F
RECURRENCE-ID;TZID=America/Los_Angeles:20141111T093000
DTSTART;TZID=America/Los_Angeles:20141111T110000
DTEND;TZID=America/Los_Angeles:20141111T120000
CREATED:20141106T192546Z
DTSTAMP:20141106T192546Z
SEQUENCE:0
SUMMARY:repeating event
TRANSP:OPAQUE
END:VEVENT
BEGIN:VEVENT
UID:CB194340-9B3C-40B1-B4E2-062FDB7C8829
DTSTART;TZID=America/Los_Angeles:20141108T080000
DTEND;TZID=America/Los_Angeles:20141108T091500
CREATED:20141104T205338Z
DTSTAMP:20141104T205338Z
SEQUENCE:0
SUMMARY:new event
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
"""


DATA_WITH_ORGANIZER = """BEGIN:VCALENDAR
VERSION:2.0
NAME:I'm the organizer
COLOR:#0000FFFF
SOURCE;VALUE=URI:http://example.com/calendars/__uids__/user01/calendar/
PRODID:-//CALENDARSERVER.ORG//NONSGML Version 1//EN
BEGIN:VEVENT
UID:AB49C0C0-4238-41A4-8B43-F3E3DDF0E59C
DTSTART;TZID=America/Los_Angeles:20141108T053000
DTEND;TZID=America/Los_Angeles:20141108T070000
ATTENDEE;CN=User 01;CUTYPE=INDIVIDUAL;ROLE=CHAIR:urn:x-uid:user01
ATTENDEE;CN=User 02;CUTYPE=INDIVIDUAL:urn:x-uid:user02
ATTENDEE;CN=User 03;CUTYPE=INDIVIDUAL:urn:x-uid:user03
ATTENDEE;CN=Mercury Seven;CUTYPE=ROOM:urn:x-uid:mercury
CREATED:20141107T172645Z
DTSTAMP:20141107T172645Z
LOCATION:Mercury
ORGANIZER;CN=User 01:urn:x-uid:user01
SEQUENCE:0
SUMMARY:I'm the organizer
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
"""


class ImportTests(StoreTestCase):
    """
    Tests for importing data to a live store.
    """

    def configure(self):
        super(ImportTests, self).configure()
        # Enable the queue and make it fast
        self.patch(self.config.Scheduling.Options.WorkQueues, "Enabled", True)
        self.patch(self.config.Scheduling.Options.WorkQueues, "RequestDelaySeconds", 0.1)
        self.patch(self.config.Scheduling.Options.WorkQueues, "ReplyDelaySeconds", 0.1)
        self.patch(self.config.Scheduling.Options.WorkQueues, "AutoReplyDelaySeconds", 0.1)
        self.patch(self.config.Scheduling.Options.WorkQueues, "AttendeeRefreshBatchDelaySeconds", 0.1)
        self.patch(self.config.Scheduling.Options.WorkQueues, "AttendeeRefreshBatchIntervalSeconds", 0.1)


    @inlineCallbacks
    def test_ImportComponentMissingSource(self):

        component = Component.allFromString(DATA_MISSING_SOURCE)
        try:
            yield importCollectionComponent(self.store, component)
        except ImportException:
            pass
        else:
            self.fail("Did not raise ImportException")


    @inlineCallbacks
    def test_ImportComponentNoScheduling(self):

        component = Component.allFromString(DATA_NO_SCHEDULING)
        yield importCollectionComponent(self.store, component)

        txn = self.store.newTransaction()
        home = yield txn.calendarHomeWithUID("user01")
        collection = yield home.childWithName("calendar")

        # Verify properties have been set
        collectionProperties = collection.properties()
        for element, value in (
            (davxml.DisplayName, "Sample Import Calendar"),
            (customxml.CalendarColor, "#0E61B9FF"),
        ):
            self.assertEquals(
                value,
                collectionProperties[PropertyName.fromElement(element)]
            )

        # Verify child objects
        objects = yield collection.listObjectResources()
        self.assertEquals(len(objects), 2)

        yield txn.commit()

        # Reimport different component into same collection

        component = Component.allFromString(DATA_NO_SCHEDULING_REIMPORT)

        yield importCollectionComponent(self.store, component)

        txn = self.store.newTransaction()
        home = yield txn.calendarHomeWithUID("user01")
        collection = yield home.childWithName("calendar")

        # Verify properties have been changed
        collectionProperties = collection.properties()
        for element, value in (
            (davxml.DisplayName, "Sample Import Calendar Reimported"),
            (customxml.CalendarColor, "#FFFFFFFF"),
        ):
            self.assertEquals(
                value,
                collectionProperties[PropertyName.fromElement(element)]
            )

        # Verify child objects (should be 3 now)
        objects = yield collection.listObjectResources()
        self.assertEquals(len(objects), 3)

        yield txn.commit()


    @inlineCallbacks
    def test_ImportComponentOrganizer(self):

        component = Component.allFromString(DATA_WITH_ORGANIZER)
        yield importCollectionComponent(self.store, component)

        yield JobItem.waitEmpty(self.store.newTransaction, reactor, 60)

        txn = self.store.newTransaction()
        home = yield txn.calendarHomeWithUID("user01")
        collection = yield home.childWithName("calendar")

        # Verify properties have been set
        collectionProperties = collection.properties()
        for element, value in (
            (davxml.DisplayName, "I'm the organizer"),
            (customxml.CalendarColor, "#0000FFFF"),
        ):
            self.assertEquals(
                value,
                collectionProperties[PropertyName.fromElement(element)]
            )

        # Verify the organizer's child objects
        objects = yield collection.listObjectResources()
        self.assertEquals(len(objects), 1)

        # Verify the attendees' child objects
        home = yield txn.calendarHomeWithUID("user02")
        collection = yield home.childWithName("calendar")
        objects = yield collection.listObjectResources()
        self.assertEquals(len(objects), 1)

        home = yield txn.calendarHomeWithUID("user03")
        collection = yield home.childWithName("calendar")
        objects = yield collection.listObjectResources()
        self.assertEquals(len(objects), 1)

        home = yield txn.calendarHomeWithUID("mercury")
        collection = yield home.childWithName("calendar")
        objects = yield collection.listObjectResources()
        self.assertEquals(len(objects), 1)

        yield txn.commit()
