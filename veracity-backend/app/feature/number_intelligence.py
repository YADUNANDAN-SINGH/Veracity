# The core feature of the this file is to get basic infromation about the number like geo location and other public data awalable for the number.

import phonenumbers as pn
from phonenumbers import geocoder, carrier, timezone

''' 
<------ For Testing ------->

NB = input("please Enter your number: ")

parsed_nb = pn.parse(NB, "IN")

if pn.is_valid_number(parsed_nb):
    print("Valid number")
else:
    print("Invalid number")

print("Here is it's e164 format: ", pn.format_number(parsed_nb, pn.PhoneNumberFormat.E164))

'''

''' 
def get_number_details(raw: str, default_region: str = "IN"):
    n = pn.parse(raw, default_region)
    
    return {
        "valid": pn.is_valid_number(n),
        "number_type": pn.number_type(n),
        "country": geocoder.country_name_for_number(n, "en"),
        "original_carrier": carrier.name_for_number(n, "en"),
        "is_international": n.country_code != 91,
        "e164_format": pn.format_number(n, pn.PhoneNumberFormat.E164),
        "national_digits": str(n.national_number)
    }
'''

# <------- Real Implementation --------->

class InvalidNumberError(ValueError):
    """Raised when the input can't be read as a phone number at all."""


def get_number_details(raw: str, default_region: str = "IN"):
    default_region = default_region.upper()

    try:
        n = pn.parse(raw, default_region)
    except pn.NumberParseException as e:
        raise InvalidNumberError("That doesn't look like a phone number.") from e

    return {
        "valid": pn.is_valid_number(n),
        # e.g. "MOBILE", "FIXED_LINE", "VOIP" (pn.number_type() alone is just an int)
        "number_type": pn.PhoneNumberType.to_string(pn.number_type(n)),
        "country": geocoder.country_name_for_number(n, "en") or None,
        # Finer than country: for Indian mobiles this is usually the telecom circle / state
        "location": geocoder.description_for_number(n, "en") or None,
        # Carrier the number was first issued to; ported numbers may have moved since
        "original_carrier": carrier.name_for_number(n, "en") or None,
        "is_international": n.country_code != pn.country_code_for_region(default_region),
        "e164_format": pn.format_number(n, pn.PhoneNumberFormat.E164),
        "national_digits": str(n.national_number),
        # phonenumbers returns ["Etc/Unknown"] when it can't tell
        "timezones": [tz for tz in timezone.time_zones_for_number(n) if tz != "Etc/Unknown"],
    }
