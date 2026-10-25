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