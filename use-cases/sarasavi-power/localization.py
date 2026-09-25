"""Shared English, Sinhala, and Tamil product vocabulary.

Numeric calculation stays in ``engine``. This module only localizes labels,
appliance display names, and curated saving advice returned by tools or demos.
"""

from __future__ import annotations

import copy
import os
import re
import sys

SUPPORTED_LANGUAGES = ("en", "si", "ta")

LANGUAGE_LABELS = {
    "en": "English",
    "si": "සිංහල",
    "ta": "தமிழ்",
}

LANGUAGE_EXAMPLE_PROMPTS = {
    "en": "I want to estimate my electricity bill.",
    "si": "මගේ විදුලි බිල ඇස්තමේන්තු කිරීමට අවශ්‍යයි.",
    "ta": "என் மின்சாரக் கட்டணத்தை மதிப்பிட வேண்டும்.",
}

# Colloquial spoken names (voice notes / calls use these heavily). Keys are
# casefolded; Sinhala entries are matched after stripping a trailing " එක".
# NOTE: first-pass vocabulary — extend with native-speaker review before launch.
SPOKEN_ALIASES: dict[str, str] = {
    # Sinhala
    "ෆ්‍රිජ්": "refrigerator",
    "අයිස් පෙට්ටිය": "refrigerator",
    "ඒසී": "air_conditioner",
    "ඒ.සී.": "air_conditioner",
    "ෆෑන්": "ceiling_fan",
    "පංකාව": "ceiling_fan",
    "බල්බ්": "led_bulb",
    "බල්බය": "led_bulb",
    "ටීවී": "tv_led",
    "ඉස්ත්‍රික්කුව": "iron",
    "රයිස් කුකර්": "rice_cooker",
    "බත් කුකර්": "rice_cooker",
    "වොෂින් මැෂින්": "washing_machine",
    "වතුර මෝටරය": "water_pump",
    "වතුර පොම්පය": "water_pump",
    "ගීසර්": "water_heater",
    "චාජර්": "phone_charger",
    "රවුටර්": "wifi_router",
    "ලැප්ටොප්": "laptop",
    # Tamil
    "ஃப்ரிட்ஜ்": "refrigerator",
    "ஏசி": "air_conditioner",
    "ஃபேன்": "ceiling_fan",
    "மின்விசிறி": "ceiling_fan",
    "பல்பு": "led_bulb",
    "டிவி": "tv_led",
    "இஸ்திரி பெட்டி": "iron",
    "ரைஸ் குக்கர்": "rice_cooker",
    "வாஷிங் மெஷின்": "washing_machine",
    "தண்ணீர் மோட்டார்": "water_pump",
    "ஹீட்டர்": "water_heater",
    "சார்ஜர்": "phone_charger",
    "ரவுட்டர்": "wifi_router",
    "லேப்டாப்": "laptop",
    # English spoken variants not already aliased in tool.py
    "aircon": "air_conditioner",
    "a/c": "air_conditioner",
    "air con": "air_conditioner",
    "television": "tv_led",
    "geyser": "water_heater",
    "motor": "water_pump",
}

APPLIANCE_NAMES: dict[str, dict[str, str]] = {
    "en": {
        "refrigerator": "Refrigerator",
        "chest_freezer": "Chest freezer",
        "air_conditioner": "Air conditioner (12k BTU)",
        "inverter_ac": "Inverter air conditioner (12k BTU)",
        "air_conditioner_18k": "Air conditioner (18k BTU)",
        "ceiling_fan": "Ceiling fan",
        "table_fan": "Table or stand fan",
        "exhaust_fan": "Exhaust fan",
        "air_cooler": "Air cooler",
        "led_bulb": "LED bulb",
        "cfl_bulb": "CFL bulb",
        "incandescent_bulb": "Filament bulb",
        "tube_light": "Fluorescent tube light",
        "led_tube": "LED tube light",
        "security_light": "Outdoor security light",
        "rice_cooker": "Rice cooker",
        "microwave": "Microwave oven",
        "electric_kettle": "Electric kettle",
        "induction_cooker": "Induction cooker",
        "electric_oven": "Electric oven",
        "toaster": "Toaster or sandwich maker",
        "blender": "Blender or grinder",
        "dishwasher": "Dishwasher",
        "water_filter": "Water purifier (RO)",
        "water_dispenser": "Water dispenser (hot and cold)",
        "washing_machine": "Washing machine",
        "clothes_dryer": "Clothes dryer",
        "iron": "Clothes iron",
        "vacuum_cleaner": "Vacuum cleaner",
        "tv_led": "LED television",
        "tv_crt": "Older CRT television",
        "set_top_box": "TV set-top box",
        "sound_system": "Sound system or home theatre",
        "desktop_computer": "Desktop computer",
        "laptop": "Laptop",
        "gaming_console": "Gaming console",
        "printer": "Printer",
        "wifi_router": "Wi-Fi router",
        "cctv_system": "CCTV system (4 cameras)",
        "phone_charger": "Phone charger",
        "power_inverter": "Home backup inverter (charging)",
        "water_heater": "Instant water heater",
        "storage_water_heater": "Storage water heater (geyser)",
        "hair_dryer": "Hair dryer",
        "water_pump": "Water pump (0.5 hp)",
        "water_pump_1hp": "Water pump (1 hp)",
        "sewing_machine": "Sewing machine",
        "mosquito_repellent": "Plug-in mosquito repellent",
        "aquarium_pump": "Aquarium pump and filter",
    },
    "si": {
        "refrigerator": "ශීතකරණය",
        "chest_freezer": "ශීතක පෙට්ටිය",
        "air_conditioner": "වායු සමීකරණ යන්ත්‍රය (12k BTU)",
        "inverter_ac": "ඉන්වර්ටර් වායු සමීකරණය (12k BTU)",
        "air_conditioner_18k": "වායු සමීකරණ යන්ත්‍රය (18k BTU)",
        "ceiling_fan": "සිවිලිම් පංකාව",
        "table_fan": "මේස පංකාව",
        "exhaust_fan": "වායු පිටකරන පංකාව",
        "air_cooler": "වායු සිසිලකය",
        "led_bulb": "LED බල්බය",
        "cfl_bulb": "CFL බල්බය",
        "incandescent_bulb": "තන්තු බල්බය",
        "tube_light": "ප්‍රතිදීප්ත නළ ආලෝකය",
        "led_tube": "LED නළ ආලෝකය",
        "security_light": "පිටත ආරක්ෂක ලාම්පුව",
        "rice_cooker": "විදුලි බත් පිසින යන්ත්‍රය",
        "microwave": "මයික්‍රෝවේව් උඳුන",
        "electric_kettle": "විදුලි කේතලය",
        "induction_cooker": "ඉන්ඩක්ෂන් උදුන",
        "electric_oven": "විදුලි උදුන",
        "toaster": "ටෝස්ටරය",
        "blender": "බ්ලෙන්ඩරය",
        "dishwasher": "පිඟන් සෝදන යන්ත්‍රය",
        "water_filter": "ජල පෙරන යන්ත්‍රය",
        "water_dispenser": "ජල බෙදාහරින යන්ත්‍රය",
        "washing_machine": "රෙදි සෝදන යන්ත්‍රය",
        "clothes_dryer": "රෙදි වේළන යන්ත්‍රය",
        "iron": "විදුලි ඉස්ත්‍රික්කය",
        "vacuum_cleaner": "රික්තක අතුගාන යන්ත්‍රය",
        "tv_led": "LED රූපවාහිනිය",
        "tv_crt": "පැරණි රූපවාහිනිය",
        "set_top_box": "රූපවාහිනී සම්බන්ධක පෙට්ටිය",
        "sound_system": "ශබ්ද පද්ධතිය",
        "desktop_computer": "ඩෙස්ක්ටොප් පරිගණකය",
        "laptop": "ලැප්ටොප් පරිගණකය",
        "gaming_console": "වීඩියෝ ක්‍රීඩා උපකරණය",
        "printer": "මුද්‍රණ යන්ත්‍රය",
        "wifi_router": "Wi-Fi රවුටරය",
        "cctv_system": "CCTV පද්ධතිය (කැමරා 4)",
        "phone_charger": "දුරකථන චාජරය",
        "power_inverter": "ගෘහ බැකප් ඉන්වර්ටරය",
        "water_heater": "ක්ෂණික ජල තාපකය",
        "storage_water_heater": "ජල තාපක ටැංකිය",
        "hair_dryer": "කෙස් වේළන යන්ත්‍රය",
        "water_pump": "ජල පොම්පය (0.5 hp)",
        "water_pump_1hp": "ජල පොම්පය (1 hp)",
        "sewing_machine": "මහන මැෂිම",
        "mosquito_repellent": "මදුරු නාශකය",
        "aquarium_pump": "මත්ස්‍ය ටැංකි පොම්පය",
    },
    "ta": {
        "refrigerator": "குளிர்சாதனப் பெட்டி",
        "chest_freezer": "உறைவிப்பான் பெட்டி",
        "air_conditioner": "குளிரூட்டி (12k BTU)",
        "inverter_ac": "இன்வர்ட்டர் குளிரூட்டி (12k BTU)",
        "air_conditioner_18k": "குளிரூட்டி (18k BTU)",
        "ceiling_fan": "மின்விசிறி",
        "table_fan": "மேசை விசிறி",
        "exhaust_fan": "வெளியேற்று விசிறி",
        "air_cooler": "காற்று குளிரூட்டி",
        "led_bulb": "LED மின்விளக்கு",
        "cfl_bulb": "CFL மின்விளக்கு",
        "incandescent_bulb": "இழை மின்விளக்கு",
        "tube_light": "ஒளிரும் குழல் விளக்கு",
        "led_tube": "LED குழல் விளக்கு",
        "security_light": "வெளிப்புற பாதுகாப்பு விளக்கு",
        "rice_cooker": "மின்சார அரிசி சமைப்பான்",
        "microwave": "நுண்ணலை அடுப்பு",
        "electric_kettle": "மின்சார கெட்டில்",
        "induction_cooker": "இண்டக்ஷன் அடுப்பு",
        "electric_oven": "மின்சார அவன்",
        "toaster": "டோஸ்டர்",
        "blender": "மிக்சி",
        "dishwasher": "பாத்திரம் கழுவும் இயந்திரம்",
        "water_filter": "நீர் சுத்திகரிப்பான்",
        "water_dispenser": "நீர் விநியோகி",
        "washing_machine": "சலவை இயந்திரம்",
        "clothes_dryer": "துணி உலர்த்தி",
        "iron": "மின்சார இஸ்திரி",
        "vacuum_cleaner": "வெற்றிட சுத்தி",
        "tv_led": "LED தொலைக்காட்சி",
        "tv_crt": "பழைய தொலைக்காட்சி",
        "set_top_box": "தொலைக்காட்சி பெட்டி",
        "sound_system": "ஒலி அமைப்பு",
        "desktop_computer": "மேசைக் கணினி",
        "laptop": "மடிக்கணினி",
        "gaming_console": "விளையாட்டு கன்சோல்",
        "printer": "அச்சுப்பொறி",
        "wifi_router": "Wi-Fi திசைவி",
        "cctv_system": "CCTV அமைப்பு (4 கேமரா)",
        "phone_charger": "கைப்பேசி மின்னேற்றி",
        "power_inverter": "வீட்டு மின் இன்வர்ட்டர்",
        "water_heater": "உடனடி நீர் சூடாக்கி",
        "storage_water_heater": "நீர் சூடாக்கும் தொட்டி",
        "hair_dryer": "தலைமுடி உலர்த்தி",
        "water_pump": "தண்ணீர் பம்ப் (0.5 hp)",
        "water_pump_1hp": "தண்ணீர் பம்ப் (1 hp)",
        "sewing_machine": "தையல் இயந்திரம்",
        "mosquito_repellent": "கொசு விரட்டி",
        "aquarium_pump": "மீன் தொட்டி பம்ப்",
    },
}

# What people actually type for an appliance, normalized the way tool.py
# normalizes input (lowercase; spaces and hyphens become underscores).
# Includes romanized Sinhala, since most people type that rather than script.
APPLIANCE_ALIASES: dict[str, str] = {
    "a_c": "air_conditioner",
    "ac": "air_conditioner",
    "ac_inverter": "inverter_ac",
    "ac_unit": "air_conditioner",
    "adsl_router": "wifi_router",
    "air_con": "air_conditioner",
    "aircon": "air_conditioner",
    "aquarium": "aquarium_pump",
    "baking_oven": "electric_oven",
    "balba": "led_bulb",
    "balbaya": "led_bulb",
    "bath_cooker": "rice_cooker",
    "bathpisina_yanthraya": "rice_cooker",
    "battery_backup": "power_inverter",
    "blow_dryer": "hair_dryer",
    "boiler": "storage_water_heater",
    "booster_pump": "water_pump",
    "bread_toaster": "toaster",
    "bulb": "led_bulb",
    "bulbs": "led_bulb",
    "cameras": "cctv_system",
    "cctv": "cctv_system",
    "ceiling_fans": "ceiling_fan",
    "cfl": "cfl_bulb",
    "charger": "phone_charger",
    "computer": "desktop_computer",
    "console": "gaming_console",
    "cooler": "air_cooler",
    "cpu": "desktop_computer",
    "crt_tv": "tv_crt",
    "deep_freezer": "chest_freezer",
    "desk_fan": "table_fan",
    "desktop": "desktop_computer",
    "desktop_pc": "desktop_computer",
    "dialog_tv": "set_top_box",
    "dish_tv": "set_top_box",
    "dryer": "clothes_dryer",
    "dvr": "cctv_system",
    "electric_iron": "iron",
    "electric_jug": "electric_kettle",
    "energy_saver": "cfl_bulb",
    "extractor_fan": "exhaust_fan",
    "fan": "ceiling_fan",
    "filament_bulb": "incandescent_bulb",
    "fish_tank": "aquarium_pump",
    "flood_light": "security_light",
    "floodlight": "security_light",
    "floor_fan": "table_fan",
    "fluorescent": "tube_light",
    "food_processor": "blender",
    "freezer": "chest_freezer",
    "fridge": "refrigerator",
    "fridge_freezer": "refrigerator",
    "gaming_pc": "desktop_computer",
    "geyser": "storage_water_heater",
    "grill": "toaster",
    "grinder": "blender",
    "hairdryer": "hair_dryer",
    "heater": "water_heater",
    "home_theater": "sound_system",
    "home_theatre": "sound_system",
    "hoover": "vacuum_cleaner",
    "hot_plate": "induction_cooker",
    "hot_water": "water_heater",
    "induction": "induction_cooker",
    "induction_hob": "induction_cooker",
    "internet_router": "wifi_router",
    "inverter": "power_inverter",
    "inverter_air_conditioner": "inverter_ac",
    "iron_box": "iron",
    "ironing": "iron",
    "isthrikka": "iron",
    "isthrikkaya": "iron",
    "jala_pompaya": "water_pump",
    "jug": "electric_kettle",
    "juicer": "blender",
    "kettle": "electric_kettle",
    "kitchen_fan": "exhaust_fan",
    "lamp": "led_bulb",
    "laptops": "laptop",
    "laundry_machine": "washing_machine",
    "led": "led_bulb",
    "led_bulbs": "led_bulb",
    "led_tv": "tv_led",
    "light": "led_bulb",
    "lights": "led_bulb",
    "macbook": "laptop",
    "machine": "sewing_machine",
    "mixer": "blender",
    "mixie": "blender",
    "mobile_charger": "phone_charger",
    "modem": "wifi_router",
    "mosquito_killer": "mosquito_repellent",
    "mosquito_mat": "mosquito_repellent",
    "motor": "water_pump",
    "notebook": "laptop",
    "nvr": "cctv_system",
    "old_tv": "tv_crt",
    "outdoor_light": "security_light",
    "oven": "electric_oven",
    "paka": "ceiling_fan",
    "pankawa": "ceiling_fan",
    "pankha": "ceiling_fan",
    "parigganakaya": "desktop_computer",
    "pc": "desktop_computer",
    "pedestal_fan": "table_fan",
    "peo_tv": "set_top_box",
    "peotv": "set_top_box",
    "phone": "phone_charger",
    "playstation": "gaming_console",
    "pompaya": "water_pump",
    "printer_scanner": "printer",
    "ps4": "gaming_console",
    "ps5": "gaming_console",
    "pump": "water_pump",
    "purifier": "water_filter",
    "radio": "sound_system",
    "redi_sodana_yanthraya": "washing_machine",
    "ro": "water_filter",
    "ro_filter": "water_filter",
    "roof_fan": "ceiling_fan",
    "router": "wifi_router",
    "rupavahini": "tv_led",
    "rupavahiniya": "tv_led",
    "sandwich_maker": "toaster",
    "scanner": "printer",
    "security_camera": "cctv_system",
    "settop_box": "set_top_box",
    "setup_box": "set_top_box",
    "sewing": "sewing_machine",
    "sheethakaranaya": "refrigerator",
    "shower_heater": "water_heater",
    "sithakaranaya": "refrigerator",
    "smart_tv": "tv_led",
    "speaker": "sound_system",
    "speakers": "sound_system",
    "split_ac": "air_conditioner",
    "stand_fan": "table_fan",
    "standing_fan": "table_fan",
    "stereo": "sound_system",
    "table_fans": "table_fan",
    "television": "tv_led",
    "tube": "tube_light",
    "tube_tv": "tv_crt",
    "tubelight": "tube_light",
    "tumble_dryer": "clothes_dryer",
    "tv": "tv_led",
    "ups": "power_inverter",
    "vacuum": "vacuum_cleaner",
    "wall_fan": "table_fan",
    "washer": "washing_machine",
    "washing": "washing_machine",
    "water_cooler": "water_dispenser",
    "water_heater_tank": "storage_water_heater",
    "water_motor": "water_pump",
    "well_pump": "water_pump",
    "wifi": "wifi_router",
    "xbox": "gaming_console",
}

SAVING_TIPS: dict[str, dict[str, list[str]]] = {
    "en": {
        "air_conditioner": [
            "Set the AC to 26-27 C instead of 22 C; each degree can reduce its energy use.",
            "Clean the AC filter monthly so the compressor does not run longer than necessary.",
            "Use a fan with the AC so you can raise the thermostat comfortably.",
        ],
        "water_heater": [
            "Heat water only just before use instead of leaving the heater on.",
            "A lower safe thermostat setting reduces standing heat loss.",
        ],
        "refrigerator": [
            "Leave ventilation space around the fridge and keep it away from the cooker.",
            "Check the fridge door seal; a weak seal makes the compressor run longer.",
        ],
        "ceiling_fan": [
            "Switch ceiling fans off when a room is empty.",
            "Use the lowest comfortable fan speed and clean the blades regularly.",
        ],
        "led_bulb": ["Turn off LED bulbs in unoccupied rooms even though each bulb uses little power."],
        "iron": ["Iron a full batch of clothes in one session while the plate is already hot."],
        "lighting": ["Replace remaining tube or incandescent lights with LED bulbs."],
        "general": [
            "Switch off appliances at the wall when safe; standby consumption adds up.",
            "Run the washing machine with a full load instead of several small loads.",
        ],
    },
    "si": {
        "air_conditioner": [
            "වායු සමීකරණය 22°C වෙනුවට 26-27°C ලෙස සකසන්න; උෂ්ණත්වය අංශකයකින් වැඩි කිරීමෙන් බලශක්ති භාවිතය අඩු කළ හැක.",
            "කම්ප්‍රෙසරය අනවශ්‍ය ලෙස දිගු වේලාවක් ක්‍රියා නොකිරීමට වායු පෙරහන මාසිකව පිරිසිදු කරන්න.",
            "වායු සමීකරණය සමඟ පංකාවක් භාවිතා කර සුවපහසු ලෙස උෂ්ණත්ව සැකසුම වැඩි කරන්න.",
        ],
        "water_heater": [
            "ජල තාපකය දිගටම ක්‍රියාත්මක නොකර භාවිතයට පෙර පමණක් ජලය උණු කරන්න.",
            "ආරක්ෂිත අඩු උෂ්ණත්ව සැකසුමක් භාවිතා කිරීමෙන් තාප හානි අඩු වේ.",
        ],
        "refrigerator": [
            "ශීතකරණය වටා වාතාශ්‍රය සඳහා ඉඩ තබා උදුනෙන් ඈත් කර තබන්න.",
            "ශීතකරණ දොරේ රබර් මුද්‍රාව පරීක්ෂා කරන්න; දුර්වල මුද්‍රාවක් නිසා කම්ප්‍රෙසරය වැඩි වේලාවක් ක්‍රියා කරයි.",
        ],
        "ceiling_fan": [
            "කාමරය හිස් වන විට සිවිලිම් පංකා නිවා දමන්න.",
            "සුවපහසු අවම පංකා වේගය භාවිතා කර තල නිතර පිරිසිදු කරන්න.",
        ],
        "led_bulb": ["එක් බල්බයක් අඩු විදුලියක් භාවිතා කළත්, භාවිතා නොකරන කාමරවල LED බල්බ නිවා දමන්න."],
        "iron": ["තැටිය උණු වී ඇති අතරතුර ඇඳුම් සියල්ල එකවර ඉස්ත්‍රික්ක කරන්න."],
        "lighting": ["ඉතිරි නළ හෝ තාපදීප්ත විදුලි පහන් LED බල්බවලින් මාරු කරන්න."],
        "general": [
            "ආරක්ෂිත විට භාවිතා නොකරන උපකරණ බිත්ති ස්විචයෙන් නිවා දමන්න; ස්ටෑන්ඩ්බයි පරිභෝජනය එකතු වේ.",
            "කුඩා වාර කිහිපයක් වෙනුවට සම්පූර්ණ බරක් සමඟ රෙදි සෝදන යන්ත්‍රය ධාවනය කරන්න.",
        ],
    },
    "ta": {
        "air_conditioner": [
            "குளிரூட்டியை 22°Cக்கு பதிலாக 26-27°Cல் அமைக்கவும்; ஒவ்வொரு டிகிரி உயர்வும் மின்சாரப் பயன்பாட்டைக் குறைக்க உதவும்.",
            "கம்ப்ரசர் தேவையற்ற நேரம் இயங்காமல் இருக்க காற்று வடிகட்டியை மாதந்தோறும் சுத்தம் செய்யவும்.",
            "குளிரூட்டியுடன் மின்விசிறியைப் பயன்படுத்தி வெப்பநிலை அமைப்பை வசதியாக உயர்த்தவும்.",
        ],
        "water_heater": [
            "நீர் சூடாக்கியை தொடர்ந்து இயக்காமல், பயன்படுத்துவதற்கு முன் மட்டும் நீரைச் சூடாக்கவும்.",
            "பாதுகாப்பான குறைந்த வெப்பநிலை அமைப்பு நிலையான வெப்ப இழப்பைக் குறைக்கும்.",
        ],
        "refrigerator": [
            "குளிர்சாதனப் பெட்டியைச் சுற்றி காற்றோட்ட இடம் விட்டு, அடுப்பிலிருந்து தள்ளி வைக்கவும்.",
            "கதவு முத்திரையைச் சரிபார்க்கவும்; பலவீனமான முத்திரை கம்ப்ரசரை நீண்ட நேரம் இயக்கும்.",
        ],
        "ceiling_fan": [
            "அறையில் யாரும் இல்லாதபோது மின்விசிறிகளை அணைக்கவும்.",
            "வசதியான குறைந்த வேகத்தைப் பயன்படுத்தி விசிறி இறக்கைகளைத் தொடர்ந்து சுத்தம் செய்யவும்.",
        ],
        "led_bulb": ["ஒவ்வொரு LED விளக்கும் குறைந்த மின்சாரம் பயன்படுத்தினாலும், காலியான அறைகளில் அவற்றை அணைக்கவும்."],
        "iron": ["இஸ்திரி சூடாக இருக்கும் போதே துணிகளை ஒரே தடவையில் இஸ்திரி செய்யவும்."],
        "lighting": ["மீதமுள்ள குழல் அல்லது இழை விளக்குகளை LED விளக்குகளாக மாற்றவும்."],
        "general": [
            "பாதுகாப்பான போது பயன்படுத்தாத சாதனங்களை சுவர் சுவிட்சில் அணைக்கவும்; காத்திருப்பு மின்சாரம் சேர்ந்து விடும்.",
            "பல சிறிய சலவைகளுக்கு பதிலாக முழு சுமையுடன் சலவை இயந்திரத்தை இயக்கவும்.",
        ],
    },
}

# A savings answer is easy to read and forget; closing it with a short, numbered
# plan gives the household something to actually go DO. Fully pre-formatted here
# (like every other money/kWh figure in this app) so build_savings_plan() below
# just fills in numbers the engine already computed -- the model relays it
# verbatim rather than composing its own, which is where a plan would drift.
PLAN_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "heading": "Your action plan:",
        "boundary_step": "Cut {cut:.2f} kWh to reach {target:.0f} kWh this cycle: staying under that tariff "
        "block alone saves {currency} {saving:,.2f}.",
        "appliance_step": "Cut back on {name} ({share:.0f}% of your usage): {tip}",
        "general_step": "{tip}",
        "recheck_step": "Send your next meter reading before this cycle ends so we can confirm you hit the target.",
    },
    "si": {
        "heading": "ඔබේ ක්‍රියාකාරී සැලැස්ම:",
        "boundary_step": "{target:.0f} kWh දක්වා යාමට {cut:.2f} kWh අඩු කරන්න: එම ගාස්තු කාණ්ඩයට පහළින් සිටීම "
        "නිසාම {currency} {saving:,.2f} ඉතිරි වේ.",
        "appliance_step": "{name} භාවිතය අඩු කරන්න (ඔබේ පරිභෝජනයෙන් {share:.0f}%ක්): {tip}",
        "general_step": "{tip}",
        "recheck_step": "ඉලක්කයට ළඟා වුනාද බැලීමට, මෙම බිල් කාලය අවසන් වීමට පෙර මීළඟ මීටර් කියවීම එවන්න.",
    },
    "ta": {
        "heading": "உங்கள் செயல் திட்டம்:",
        "boundary_step": "{target:.0f} kWh-ஐ அடைய {cut:.2f} kWh குறைக்கவும்: அந்தக் கட்டணப் படிக்குக் கீழே "
        "திரும்புவதால் மட்டும் {currency} {saving:,.2f} சேமிக்கலாம்.",
        "appliance_step": "{name} பயன்பாட்டைக் குறைக்கவும் (உங்கள் பயன்பாட்டில் {share:.0f}%): {tip}",
        "general_step": "{tip}",
        "recheck_step": "இலக்கை அடைந்தீர்களா எனப் பார்க்க, இந்தக் காலம் முடிவதற்குள் உங்கள் அடுத்த மீட்டர் "
        "அளவீட்டை அனுப்பவும்.",
    },
}

UI_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "banner": "Sarasavi Power - keyless product demo",
        "billing_period": "Billing period",
        "days": "days",
        "usage": "Usage",
        "metered": "meter reading",
        "estimated": "appliance estimate",
        "tariff_slab": "Tariff slab",
        "effective": "effective",
        "bill": "Estimated bill",
        "loads": "Largest estimated loads:",
        "opportunity": "Best tariff-boundary opportunity:",
        "cut": "Cut {cut:.2f} kWh to reach {target:.0f} kWh; estimated bill becomes LKR {bill:,.2f} (save LKR {saving:,.2f}).",
        "no_opportunity": "No lower tariff boundary is available at this usage level.",
        "disclaimer": "Estimate only - not an official CEB/LECO bill.",
        "next": "Use demo.py for the Agent Kernel conversation and app.py after adding Meta credentials.",
    },
    "si": {
        "banner": "සරසවි පවර් - API යතුරු රහිත ආදර්ශය",
        "billing_period": "බිල් කාලය",
        "days": "දින",
        "usage": "පරිභෝජනය",
        "metered": "මීටර් කියවීම",
        "estimated": "උපකරණ ඇස්තමේන්තුව",
        "tariff_slab": "ගාස්තු කාණ්ඩය",
        "effective": "බලපැවැත්වෙන දිනය",
        "bill": "ඇස්තමේන්තුගත බිල",
        "loads": "වැඩිම ඇස්තමේන්තුගත පරිභෝජන:",
        "opportunity": "හොඳම ගාස්තු සීමා ඉතිරි කිරීම:",
        "cut": "{target:.0f} kWh දක්වා යාමට {cut:.2f} kWh අඩු කරන්න; ඇස්තමේන්තුගත බිල රුපියල් {bill:,.2f} වන අතර රුපියල් {saving:,.2f} ඉතිරි වේ.",
        "no_opportunity": "මෙම පරිභෝජන මට්ටමේදී අඩු ගාස්තු සීමාවක් නොමැත.",
        "disclaimer": "මෙය ඇස්තමේන්තුවක් පමණි - නිල CEB/LECO බිලක් නොවේ.",
        "next": "Agent Kernel සංවාදය සඳහා demo.py භාවිතා කරන්න; Meta තොරතුරු එක් කළ පසු app.py භාවිතා කරන්න.",
    },
    "ta": {
        "banner": "சரசவி பவர் - API சாவி இல்லாத செயல்முறை விளக்கம்",
        "billing_period": "கட்டணக் காலம்",
        "days": "நாட்கள்",
        "usage": "பயன்பாடு",
        "metered": "மீட்டர் அளவீடு",
        "estimated": "சாதன மதிப்பீடு",
        "tariff_slab": "கட்டணப் படிநிலை",
        "effective": "அமல்படும் தேதி",
        "bill": "மதிப்பிடப்பட்ட கட்டணம்",
        "loads": "அதிக மதிப்பிடப்பட்ட பயன்பாடுகள்:",
        "opportunity": "சிறந்த கட்டண எல்லைச் சேமிப்பு:",
        "cut": "{target:.0f} kWh-ஐ அடைய {cut:.2f} kWh குறைக்கவும்; மதிப்பிடப்பட்ட கட்டணம் ரூபாய் {bill:,.2f}, சேமிப்பு ரூபாய் {saving:,.2f}.",
        "no_opportunity": "இந்தப் பயன்பாட்டு நிலையில் குறைந்த கட்டண எல்லை இல்லை.",
        "disclaimer": "இது ஒரு மதிப்பீடு மட்டுமே - அதிகாரப்பூர்வ CEB/LECO கட்டணம் அல்ல.",
        "next": "Agent Kernel உரையாடலுக்கு demo.py-ஐ பயன்படுத்தவும்; Meta விவரங்களைச் சேர்த்த பிறகு app.py-ஐ பயன்படுத்தவும்.",
    },
}


# The currency word written in each language's own script. English keeps the ISO
# code; a Sinhala or Tamil sentence never carries "LKR", because readers say it
# as the English letters (and so does every TTS voice: එල් කේ ආර්).
CURRENCY_WORDS = {"en": "LKR", "si": "රුපියල්", "ta": "ரூபாய்"}


def currency_word(language: str | None) -> str:
    return CURRENCY_WORDS[normalize_language(language)]


def normalize_language(language: str | None) -> str:
    return language if language in SUPPORTED_LANGUAGES else "en"


def detect_language(text: str) -> str | None:
    """Detect Sinhala/Tamil script or an explicit language-selection phrase."""
    if any("\u0d80" <= char <= "\u0dff" for char in text):
        return "si"
    if any("\u0b80" <= char <= "\u0bff" for char in text):
        return "ta"

    normalized = re.sub(r"[^a-z]+", " ", text.lower()).strip()
    if re.search(r"\b(sinhala|sinhalese)\b", normalized):
        return "si"
    if re.search(r"\btamil\b", normalized):
        return "ta"
    if normalized == "english" or re.search(r"\b(in|speak|use|switch to) english\b", normalized):
        return "en"
    return None


def appliance_name(key: str, language: str, fallback: str | None = None) -> str:
    language = normalize_language(language)
    return APPLIANCE_NAMES[language].get(key) or APPLIANCE_NAMES["en"].get(key) or fallback or key


def appliance_key_from_name(name: str) -> str | None:
    candidate = name.strip().casefold()
    # Drop the Sinhala definite marker so spoken forms like "ෆෑන් එක" match "ෆෑන්".
    if candidate.endswith(" එක"):
        candidate = candidate[: -len(" එක")].strip()
    for names in APPLIANCE_NAMES.values():
        for key, localized in names.items():
            if candidate == localized.casefold():
                return key
    return SPOKEN_ALIASES.get(candidate)


def localize_breakdown(result: dict, language: str) -> dict:
    localized = copy.deepcopy(result)
    for item in localized.get("breakdown", []):
        item["name"] = appliance_name(item["key"], language, item.get("name"))
    return localized


def tips_for(key: str, language: str) -> list[str]:
    language = normalize_language(language)
    return list(SAVING_TIPS[language].get(key, []))


def matching_tips(query: str, language: str) -> list[str]:
    language = normalize_language(language)
    query_folded = query.casefold()
    matched: list[str] = []
    for key in SAVING_TIPS[language]:
        localized = appliance_name(key, language, key).casefold()
        if key in query_folded or localized in query_folded or any(word in query_folded for word in key.split("_")):
            matched.extend(tips_for(key, language))
    return matched or tips_for("general", language)


def build_savings_plan(language: str, top_boundary: dict | None, top_appliances: list[dict]) -> str:
    """A short, numbered, ready-to-send action plan closing out a savings answer.

    Every number here already came from the engine (top_boundary/top_appliances
    are find_savings()'s own output), so this only assembles and translates --
    the model appends the result verbatim instead of composing a plan itself,
    the same determinism guarantee every other figure in this app gets.
    Degrades gracefully: no boundary win, or no appliance breakdown (a metered-only
    household), still yields a sensible plan.
    """
    language = normalize_language(language)
    t = PLAN_TEXT[language]
    steps: list[str] = []

    if top_boundary:
        steps.append(
            t["boundary_step"].format(
                cut=top_boundary["units_to_cut"],
                target=top_boundary["target_units"],
                currency=currency_word(language),
                saving=top_boundary["savings"],
            )
        )

    for item in top_appliances[:2]:
        tip_list = tips_for(item["key"], language) or tips_for("general", language)
        if not tip_list:
            continue
        steps.append(
            t["appliance_step"].format(
                name=appliance_name(item["key"], language, item.get("name")),
                share=item.get("share_pct", 0),
                tip=tip_list[0],
            )
        )

    if not steps:  # neither a boundary win nor a known appliance to single out
        general = tips_for("general", language)
        if general:
            steps.append(t["general_step"].format(tip=general[0]))

    steps.append(t["recheck_step"])
    numbered = [f"{i}. {step}" for i, step in enumerate(steps, start=1)]
    return t["heading"] + "\n" + "\n".join(numbered)


def ui_text(language: str, key: str) -> str:
    return UI_TEXT[normalize_language(language)][key]


def configure_utf8_console() -> None:
    """Enable Sinhala/Tamil input and output in the Windows console."""
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleCP(65001)
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except (AttributeError, OSError):
            pass
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass
