import json
import locale
import time
from dataclasses import dataclass
from datetime import datetime as dt
from json import JSONDecoder
from json import JSONEncoder

import chardet
import unidecode
from bs4 import BeautifulSoup
from requests import get

locale.setlocale(locale.LC_ALL, 'es_ES.UTF-8')


def _remove_prefix(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix):]
    return text  # or whatever


class _CustomEncoder(JSONEncoder):
    def default(self, obj):
        return obj.__dict__


class _CustomDecoder(JSONDecoder):
    def __init__(self):
        json.JSONDecoder.__init__(self, object_hook=self.dict_to_object)

    def dict_to_object(self, d):
        if 'telephone' in d and 'webSite' in d:
            return Contact(telephone=d['telephone'], web=d['webSite'])
        if 'latitude' in d and 'longitude' in d:
            return Location(latitude=d['latitude'], longitude=d['longitude'])
        id = d['id']
        name = d['name']
        address = d['address']
        contact = d['contact']
        location = d['location']
        return Pharmacy(id=id, name=name, address=address, contact=contact, location=location)


@dataclass
class Contact:
    telephone: str = None
    web: str = None

    def __init__(self, telephone, web):
        self.telephone = telephone
        self.web = web

    def __iter__(self):
        yield from {
            "telephone": self.telephone,
            "web": self.web
        }.items()


@dataclass
class Location:
    latitude: float
    longitude: float

    def __init__(self, latitude, longitude):
        self.latitude = latitude
        self.longitude = longitude

    def __iter__(self):
        yield from {
            "latitude": self.latitude,
            "longitude": self.longitude
        }.items()


@dataclass
class Pharmacy:
    id: str
    name: str
    address: str = None
    contact: Contact = None
    location: Location = None

    def __init__(self, id, name, address, contact, location):
        self.id = id
        self.name = name
        self.address = address
        self.contact = contact
        self.location = location

    def __iter__(self):
        yield from {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "contact": self.contact,
            "location": self.location
        }.items()


@dataclass
class _OnGuardPharmacy:
    date: str
    address: str
    phone: str

    def __init__(self, date, address, phone):
        self.date = date
        self.address = address
        self.phone = phone

    def __iter__(self):
        yield from {
            "date": self.date,
            "address": self.address,
            "phone": self.phone
        }.items()

    def __str__(self):
        return json.dumps(dict(self), ensure_ascii=False)

    def __repr__(self):
        return self.__str__()


on_guard_url = 'https://www.aranjuez.es/farmacias-guardia/'


def _fetch_pharmacies_on_guard():
    response = get(on_guard_url)
    text = response.text
    soup = BeautifulSoup(text, 'html.parser')

    entry_div = soup.find('div', {'class': 'entry'})
    children = entry_div.findChildren("p")

    is_processing_month = False
    current_month = ""
    pharmacies = []
    for child in children:
        if is_processing_month is False and child.next_element.name == 'strong':
            current_month = child.next_element.text.strip()
            is_processing_month = True
        elif is_processing_month is True and current_month != "":
            entries = child.findChildren("strong")
            for entry in entries:
                if entry.text.startswith('+'):
                    continue
                day = entry.text.split(",")
                if len(day) < 2:
                    continue
                day_name = unidecode.unidecode(day[0].strip().lower())
                if day_name == 'mia(c)rcoles':
                    day_name = "miercoles"
                elif day_name == 'sa!bado':
                    day_name = "sabado"
                date = current_month + " " + day[1].strip().lower()  # Viernes, 30
                pharmacy_data = entry.nextSibling.strip().strip()
                if pharmacy_data.startswith(":"):
                    pharmacy_data = _remove_prefix(pharmacy_data, ":").strip()
                guess_year = [dt.now().year, dt.now().year - 1, dt.now().year + 1]
                for year in guess_year:
                    date_string = str(year) + " " + date
                    possible_date = dt.strptime(date_string, '%Y %B %d')
                    possible_date_day = unidecode.unidecode(possible_date.strftime("%A").lower())
                    if possible_date_day == day_name:
                        guard_day = possible_date.strftime("%d/%m/%Y")
                        pharmacy_info = pharmacy_data.split("–")
                        pharmacy_street = pharmacy_info[0] \
                            .replace('Â', '') \
                            .replace('Ã', 'í') \
                            .replace(u'\xa0', u' ') \
                            .replace('c/', '') \
                            .replace(',', '') \
                            .replace('avd.', 'Avd.') \
                            .strip()
                        if len(pharmacy_info) > 1 and pharmacy_info[1].strip().startswith("Tel.:"):
                            pharmacy_tel = _remove_prefix(pharmacy_info[1].strip(), "Tel.:")\
                                .replace('Â', '') \
                                .replace('Ã', '') \
                                .replace(u'\xa0', '') \
                                .replace(u'\xa0', u'')\
                                .replace(' ', '').strip()
                            pharmacy_tel = "+34" + pharmacy_tel
                            pharmacies.append(
                                _OnGuardPharmacy(guard_day, pharmacy_street, pharmacy_tel))
                            break
                        else:
                            pharmacies.append(_OnGuardPharmacy(guard_day, pharmacy_street, None))
                            break
            is_processing_month = False
    return pharmacies


def update_pharmacies_data_set():
    with open('data/pharmacies/pharmacies.json') as pharmaciesFile:
        pharmacies = json.load(pharmaciesFile, cls=_CustomDecoder)
        if len(pharmacies) == 0:
            return
        on_guard_data = _fetch_pharmacies_on_guard()
        on_guard_calendar = {}
        for po in on_guard_data:
            found = False
            for p in pharmacies:
                if po.phone == p.contact.telephone:
                    on_guard_calendar[po.date] = [p.id]
                    found = True
                    break
            if found is False:
                if po.address in p.address:
                    on_guard_calendar[po.date] = [p.id]
                    found = True
                    break
        if len(on_guard_calendar) > 0:
            with open('data/pharmacies/pharmacies_calendar.json', 'w') as outfile:
                data = {
                    "updated": time.time(),
                    "source": on_guard_url,
                    "calendar": on_guard_calendar,
                }
                json_string = json.dumps(data, cls=_CustomEncoder, indent=4, separators=(", ", ": "), sort_keys=True,
                                         allow_nan=False, ensure_ascii=False)
                outfile.write(json_string)
