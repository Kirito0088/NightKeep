"""English and Marathi for the console's chrome and headings.

Scope, by decision: navigation, the utility strip, the demo controls,
breadcrumbs, page and panel headings, the main status headlines, table
column headers, form labels and buttons. Body sentences and every record
(names, card numbers, verdict reasons) stay as they are.

The Marathi is modern, everyday office Marathi, the way a clerk at a
district supply office actually talks: short sentences, and the English
words people already use written in Devanagari (रेशन कार्ड, डेटा, बॅकअप,
रिस्टोर, डेमो, स्टेटस) rather than formal coinages nobody says aloud.

The English text is the key. Anything not in the catalogue falls back to
English, so a missing entry can never break a page. The team's Marathi
speakers should proofread this file before it is shown to judges.

The disclaimer strip is never translated away: ADR-0005 requires the
English line on every screen.
"""

from __future__ import annotations

ENGLISH = "en"
MARATHI = "mr"
LANGUAGES = (ENGLISH, MARATHI)

_MARATHI: dict[str, str] = {
    # --- navigation and chrome -------------------------------------------
    "Ration Card Search": "रेशन कार्ड शोधा",
    "Data Safety": "डेटा सुरक्षा",
    "Night Jobs": "रात्रीची कामे",
    "Full MVP Demo": "पूर्ण MVP डेमो",
    "Home": "होम",
    "Skip to main content": "मुख्य माहितीवर जा",
    "Screen Reader Access": "स्क्रीन रीडर",
    "Harvest surge": "हंगामाची गर्दी",
    "On": "चालू",
    "Off": "बंद",
    "Demo controls": "डेमो कंट्रोल्स",
    "Simulated attack": "डेमो हल्ला",
    "Run simulated attack": "डेमो हल्ला सुरू करा",
    "Start a fresh run": "पुन्हा नव्याने सुरू करा",
    "IT View": "IT व्ह्यू",
    "For the IT person": "IT टीमसाठी",

    # --- page and panel headings -------------------------------------------
    "Ration Card Search (System Protected)": "रेशन कार्ड शोधा (सिस्टम सुरक्षित)",
    "System Protected": "सिस्टम सुरक्षित",
    "Search Filters": "शोध फिल्टर",
    "Search Results": "शोध निकाल",
    "Search Unavailable": "सध्या शोध बंद आहे",
    "District Figures": "जिल्ह्याची आकडेवारी",
    "Household Details": "कुटुंबाची माहिती",
    "Family Members": "कुटुंबातील सदस्य",
    "Monthly Entitlement": "दरमहा मिळणारे धान्य",
    "ePoS Collection History": "ePoS वर धान्य घेतल्याची नोंद",
    "Ration Card Not Found": "रेशन कार्ड सापडले नाही",
    "Record Not Found": "माहिती सापडली नाही",
    "Not Found": "सापडले नाही",
    "Protection Summary": "सुरक्षेचा सारांश",
    "Night Tasks Activity": "रात्रीच्या कामांची माहिती",
    "Learning Progress": "शिकण्याची प्रगती",
    "The Night Jobs": "रात्रीची कामे",
    "Recent Checks": "अलीकडच्या तपासण्या",
    "Data Safety Alert": "डेटा सुरक्षा अलर्ट",
    "Incident Alert": "धोक्याचा अलर्ट",
    "Incident Report": "घटनेचा रिपोर्ट",
    "Incident Timeline": "घटना कशी घडली",
    "Incident figures": "घटनेची आकडेवारी",
    "Incident": "घटना",
    "What happened": "काय झाले",
    "What NightKeep did": "NightKeep ने काय केले",
    "What to do now": "आता काय करायचे",
    "What the office does next": "ऑफिसने पुढे काय करायचे",
    "Actions taken": "केलेली कारवाई",
    "Get my records back": "माझा डेटा परत मिळवा",
    "Restore": "रिस्टोर",
    "Restore Progress": "रिस्टोर कुठपर्यंत आले",
    "Restore Records": "डेटा रिस्टोर करा",
    "Safety Verification (Five Checks)": "सुरक्षा तपासणी (पाच तपासण्या)",
    "Loss Window Advisory": "पुन्हा तपासायच्या नोंदी",
    "Step 3: Authorisation and Confirmation": "पायरी 3: परवानगी आणि खात्री",
    "IT diagnostics": "IT तपासणी",
    "Vault alert records": "व्हॉल्ट अलर्टच्या नोंदी",
    "Run the demonstration": "डेमो चालवा",
    "What this demonstrates": "हा डेमो काय दाखवतो",
    "Demonstration progress": "डेमो कुठपर्यंत आला",
    "Measured on this run": "या डेमोमध्ये मोजलेले",
    "Inspect the result": "निकाल पाहा",
    "Technical output": "तांत्रिक माहिती",
    "Simulated Threat Note (Demonstration Artifact)": "डेमो धमकीची नोट (फक्त डेमोसाठी)",
    "Locked Screen": "लॉक स्क्रीन",
    "Habit": "सवय",
    "Vault": "व्हॉल्ट",
    "Watcher": "वॉचर",

    # --- status headlines ----------------------------------------------------
    "Your records are safe": "तुमचा डेटा सुरक्षित आहे",
    "Your records are back": "तुमचा डेटा परत मिळाला आहे",
    "Someone tried to lock your files. It was stopped.":
        "कोणीतरी तुमच्या फाइल्स लॉक करायचा प्रयत्न केला. त्याला थांबवले आहे.",
    "Something unusual is happening to your files.":
        "तुमच्या फाइल्समध्ये काहीतरी वेगळे घडत आहे.",
    "No incidents. Nightkeep is watching.":
        "कोणताही धोका नाही. Nightkeep लक्ष ठेवून आहे.",
    "No safe copies yet": "अजून बॅकअप कॉपी नाही",
    "Attention needed: Nightkeep is protecting your records":
        "लक्ष द्या: Nightkeep तुमचा डेटा सुरक्षित ठेवत आहे",
    "Attention needed: the latest safe copy looks suspicious":
        "लक्ष द्या: नवीन बॅकअप कॉपीमध्ये काहीतरी गडबड दिसते",
    "Attention needed: unusual activity is under review":
        "लक्ष द्या: वेगळ्या हालचालीची तपासणी सुरू आहे",
    "Ration card records cannot be opened": "रेशन कार्डचा डेटा सध्या उघडता येत नाही",
    "How the lock screen looks during an attack (drill)":
        "हल्ल्याच्या वेळी लॉक स्क्रीन अशी दिसते (सराव)",
    "Nightkeep Security Alert": "Nightkeep सुरक्षा अलर्ट",
    "A program tried to lock your files. It was paused.":
        "एका प्रोग्रामने तुमच्या फाइल्स लॉक करायचा प्रयत्न केला. त्याला थांबवले आहे.",
    "Unusual activity was detected on the office computer.":
        "ऑफिसच्या कॉम्प्युटरवर वेगळी हालचाल दिसली.",
    "Nightkeep is getting ready to watch the night jobs.":
        "Nightkeep रात्रीच्या कामांवर लक्ष ठेवायची तयारी करत आहे.",
    "Nightkeep is learning the office's night jobs.":
        "Nightkeep ऑफिसची रात्रीची कामे शिकत आहे.",
    "Nightkeep has learned the night jobs and is checking every run.":
        "Nightkeep ने रात्रीची कामे शिकली आहेत. आता प्रत्येक काम तपासले जात आहे.",
    "A safe simulated attack is running.": "सुरक्षित डेमो हल्ला सुरू आहे.",
    "Night jobs are stopped while the records are protected.":
        "डेटा सुरक्षित होईपर्यंत रात्रीची कामे थांबवली आहेत.",
    "Night jobs are stopped. The records were restored.":
        "रात्रीची कामे थांबवली आहेत. डेटा रिस्टोर झाला आहे.",
    "The full demonstration is complete.": "पूर्ण डेमो झाला आहे.",
    "The live session stopped with a problem.": "लाइव्ह सेशन एका अडचणीमुळे थांबले.",
    "The live session has stopped.": "लाइव्ह सेशन थांबले आहे.",

    # --- the Full MVP Demo's phases ---------------------------------------
    "READY": "तयार",
    "STARTING": "सुरू होत आहे",
    "LEARN": "शिकणे",
    "GUARD": "लक्ष ठेवणे",
    "ATTACK": "हल्ला",
    "CONTAIN": "हल्ला थांबवणे",
    "PROTECT": "डेटा सुरक्षित",
    "RECOVER": "डेटा परत",
    "DEMO COMPLETE": "डेमो पूर्ण",
    "DEMO FAILED": "डेमो अयशस्वी",

    # --- table column headers -------------------------------------------------
    "Card Number": "कार्ड नंबर",
    "Head of Family": "कुटुंबप्रमुख",
    "Head of family": "कुटुंबप्रमुख",
    "Taluka": "तालुका",
    "Taluka / Village": "तालुका / गाव",
    "Fair Price Shop": "रेशन दुकान",
    "Scheme": "योजना",
    "Status": "स्टेटस",
    "Sr No": "क्र.",
    "Member Name": "सदस्याचे नाव",
    "Relation to Head": "कुटुंबप्रमुखाशी नाते",
    "Sex": "लिंग",
    "Age": "वय",
    "Aadhaar Seeded": "आधार लिंक",
    "e-KYC Status": "e-KYC स्टेटस",
    "Commodity": "धान्य",
    "Monthly Allotment": "दरमहा कोटा",
    "Issue Price": "दर",
    "Allotment Basis": "कोटा कसा ठरतो",
    "Total Monthly Grain": "दरमहा एकूण धान्य",
    "Date & Time": "तारीख आणि वेळ",
    "Allotment Month": "कोट्याचा महिना",
    "Commodity / Quantity": "धान्य / वजन",
    "Authentication Mode": "ओळख कशी पटवली",
    "Task": "काम",
    "Usually": "नेहमी",
    "Last night": "काल रात्री",
    "Night job": "रात्रीचे काम",
    "What it does": "हे काम काय करते",
    "Learning": "शिकणे",
    "Last run": "शेवटचे कधी चालले",
    "Last check": "शेवटची तपासणी",
    "Day": "दिवस",
    "Result": "निकाल",
    "Why": "कारण",
    "Job": "काम",
    "Feature": "फीचर",
    "Median": "मीडियन",
    "Spread": "स्प्रेड",
    "Observations": "नोंदी",
    "Snapshot": "स्नॅपशॉट",
    "Taken at": "वेळ",
    "Health": "स्थिती",
    "Files": "फाइल्स",
    "Manifest hash": "मॅनिफेस्ट हॅश",
    "Signals": "सिग्नल",
    "Reasons": "कारणे",

    # --- form labels and buttons -----------------------------------------------
    "Ration card number": "रेशन कार्ड नंबर",
    "All Talukas": "सर्व तालुके",
    "All Schemes": "सर्व योजना",
    "All Statuses": "सर्व स्टेटस",
    "Search": "शोधा",
    "Reset Filters": "फिल्टर रीसेट करा",
    "Clear Filters": "फिल्टर काढा",
    "Back to Search": "शोधाकडे परत",
    "Back to Ration Card Search": "रेशन कार्ड शोधाकडे परत",
    "Return to Ration Card Search": "रेशन कार्ड शोधाकडे परत जा",
    "Open Data Safety": "डेटा सुरक्षा उघडा",
    "Open Vault Console (Simulation)": "व्हॉल्ट कन्सोल उघडा (डेमो)",
    "Supervisor authorisation PIN": "सुपरवायझर PIN",
    "Restore records to office computer": "डेटा ऑफिसच्या कॉम्प्युटरवर रिस्टोर करा",
    "Return to Incident Alert": "अलर्टकडे परत जा",
    "Acknowledge": "ठीक आहे",
    "Run Full MVP Demo": "पूर्ण MVP डेमो चालवा",
}


def translate(text: str, lang: str) -> str:
    """The text in the chosen language, or the English when there is none."""
    if lang != MARATHI or not isinstance(text, str):
        return text
    return _MARATHI.get(text, text)


def catalogue() -> dict[str, str]:
    """A copy of the Marathi catalogue, for tests."""
    return dict(_MARATHI)


__all__ = ["ENGLISH", "MARATHI", "LANGUAGES", "translate", "catalogue"]
