"""English and Marathi for the console's chrome and headings.

Scope, by decision: navigation, the utility strip, the demo controls,
breadcrumbs, page and panel headings, the main status headlines, table
column headers, form labels and buttons. Body sentences and every record
(names, card numbers, verdict reasons) stay as they are.

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
    "Ration Card Search": "शिधापत्रिका शोध",
    "Data Safety": "डेटा सुरक्षा",
    "Night Jobs": "रात्रीची कामे",
    "Full MVP Demo": "संपूर्ण MVP प्रात्यक्षिक",
    "Home": "मुख्यपृष्ठ",
    "Skip to main content": "मुख्य मजकुराकडे जा",
    "Screen Reader Access": "स्क्रीन रीडर सुविधा",
    "Harvest surge": "सुगीची गर्दी",
    "On": "चालू",
    "Off": "बंद",
    "Demo controls": "प्रात्यक्षिक नियंत्रणे",
    "Simulated attack": "सराव हल्ला",
    "Run simulated attack": "सराव हल्ला चालवा",
    "Start a fresh run": "नवीन सुरुवात करा",
    "IT View": "IT दृश्य",
    "For the IT person": "IT कर्मचाऱ्यांसाठी",

    # --- page and panel headings -------------------------------------------
    "Ration Card Search (System Protected)": "शिधापत्रिका शोध (प्रणाली संरक्षित)",
    "System Protected": "प्रणाली संरक्षित",
    "Search Filters": "शोध निकष",
    "Search Results": "शोध निकाल",
    "Search Unavailable": "शोध उपलब्ध नाही",
    "District Figures": "जिल्हा आकडेवारी",
    "Household Details": "कुटुंबाचा तपशील",
    "Family Members": "कुटुंबातील सदस्य",
    "Monthly Entitlement": "मासिक हक्क",
    "ePoS Collection History": "ePoS वितरण इतिहास",
    "Ration Card Not Found": "शिधापत्रिका सापडली नाही",
    "Record Not Found": "नोंद सापडली नाही",
    "Not Found": "सापडले नाही",
    "Protection Summary": "संरक्षण सारांश",
    "Night Tasks Activity": "रात्रीच्या कामांची हालचाल",
    "Learning Progress": "शिकण्याची प्रगती",
    "The Night Jobs": "रात्रीची कामे",
    "Recent Checks": "अलीकडील तपासण्या",
    "Data Safety Alert": "डेटा सुरक्षा इशारा",
    "Incident Alert": "घटना इशारा",
    "Incident Report": "घटना अहवाल",
    "Incident Timeline": "घटनेचा क्रम",
    "Incident figures": "घटनेची आकडेवारी",
    "Incident": "घटना",
    "What happened": "काय घडले",
    "What NightKeep did": "NightKeep ने काय केले",
    "What to do now": "आता काय करावे",
    "What the office does next": "कार्यालयाने पुढे काय करावे",
    "Actions taken": "केलेली कारवाई",
    "Get my records back": "माझ्या नोंदी परत मिळवा",
    "Restore": "पुनर्स्थापना",
    "Restore Progress": "पुनर्स्थापनेची प्रगती",
    "Restore Records": "नोंदी पुनर्स्थापित करा",
    "Safety Verification (Five Checks)": "सुरक्षा पडताळणी (पाच तपासण्या)",
    "Loss Window Advisory": "नुकसान कालावधी सूचना",
    "Step 3: Authorisation and Confirmation": "पायरी 3: अधिकृतता आणि पुष्टी",
    "IT diagnostics": "IT तपासणी",
    "Vault alert records": "व्हॉल्ट इशाऱ्यांच्या नोंदी",
    "Run the demonstration": "प्रात्यक्षिक चालवा",
    "What this demonstrates": "हे काय दाखवते",
    "Demonstration progress": "प्रात्यक्षिकाची प्रगती",
    "Measured on this run": "या फेरीत मोजलेले",
    "Inspect the result": "निकाल पाहा",
    "Technical output": "तांत्रिक आउटपुट",
    "Simulated Threat Note (Demonstration Artifact)": "सराव धोक्याची चिठ्ठी (प्रात्यक्षिकासाठी)",
    "Locked Screen": "लॉक केलेली स्क्रीन",
    "Habit": "सवय",
    "Vault": "व्हॉल्ट",
    "Watcher": "वॉचर",

    # --- status headlines ----------------------------------------------------
    "Your records are safe": "तुमच्या नोंदी सुरक्षित आहेत",
    "Your records are back": "तुमच्या नोंदी परत मिळाल्या आहेत",
    "Someone tried to lock your files. It was stopped.":
        "कोणीतरी तुमच्या फाइल्स लॉक करण्याचा प्रयत्न केला. तो थांबवला गेला.",
    "Something unusual is happening to your files.":
        "तुमच्या फाइल्समध्ये काहीतरी असामान्य घडत आहे.",
    "No incidents. Nightkeep is watching.":
        "कोणतीही घटना नाही. Nightkeep लक्ष ठेवून आहे.",
    "No safe copies yet": "अद्याप कोणतीही सुरक्षित प्रत नाही",
    "Attention needed: Nightkeep is protecting your records":
        "लक्ष द्या: Nightkeep तुमच्या नोंदींचे संरक्षण करत आहे",
    "Attention needed: the latest safe copy looks suspicious":
        "लक्ष द्या: नवीनतम सुरक्षित प्रत संशयास्पद दिसते",
    "Attention needed: unusual activity is under review":
        "लक्ष द्या: असामान्य हालचालीची तपासणी सुरू आहे",
    "Ration card records cannot be opened": "शिधापत्रिकेच्या नोंदी उघडता येत नाहीत",
    "How the lock screen looks during an attack (drill)":
        "हल्ल्यादरम्यान लॉक स्क्रीन कशी दिसते (सराव)",
    "Nightkeep Security Alert": "Nightkeep सुरक्षा इशारा",
    "A program tried to lock your files. It was paused.":
        "एका प्रोग्रामने तुमच्या फाइल्स लॉक करण्याचा प्रयत्न केला. तो थांबवला गेला.",
    "Unusual activity was detected on the office computer.":
        "कार्यालयीन संगणकावर असामान्य हालचाल आढळली.",
    "Nightkeep is getting ready to watch the night jobs.":
        "Nightkeep रात्रीच्या कामांवर लक्ष ठेवण्याची तयारी करत आहे.",
    "Nightkeep is learning the office's night jobs.":
        "Nightkeep कार्यालयाची रात्रीची कामे शिकत आहे.",
    "Nightkeep has learned the night jobs and is checking every run.":
        "Nightkeep ने रात्रीची कामे शिकली आहेत आणि प्रत्येक फेरी तपासत आहे.",
    "A safe simulated attack is running.": "सुरक्षित सराव हल्ला सुरू आहे.",
    "Night jobs are stopped while the records are protected.":
        "नोंदी संरक्षित असेपर्यंत रात्रीची कामे थांबवली आहेत.",
    "Night jobs are stopped. The records were restored.":
        "रात्रीची कामे थांबवली आहेत. नोंदी पुनर्स्थापित केल्या आहेत.",
    "The full demonstration is complete.": "संपूर्ण प्रात्यक्षिक पूर्ण झाले आहे.",
    "The live session stopped with a problem.": "थेट सत्र एका अडचणीमुळे थांबले.",
    "The live session has stopped.": "थेट सत्र थांबले आहे.",

    # --- the Full MVP Demo's phases ---------------------------------------
    "READY": "तयार",
    "STARTING": "सुरू होत आहे",
    "LEARN": "शिकणे",
    "GUARD": "पहारा",
    "ATTACK": "हल्ला",
    "CONTAIN": "रोखणे",
    "PROTECT": "संरक्षण",
    "RECOVER": "पुनर्प्राप्ती",
    "DEMO COMPLETE": "प्रात्यक्षिक पूर्ण",
    "DEMO FAILED": "प्रात्यक्षिक अयशस्वी",

    # --- table column headers -------------------------------------------------
    "Card Number": "शिधापत्रिका क्रमांक",
    "Head of Family": "कुटुंबप्रमुख",
    "Head of family": "कुटुंबप्रमुख",
    "Taluka": "तालुका",
    "Taluka / Village": "तालुका / गाव",
    "Fair Price Shop": "रास्त भाव दुकान",
    "Scheme": "योजना",
    "Status": "स्थिती",
    "Sr No": "अ. क्र.",
    "Member Name": "सदस्याचे नाव",
    "Relation to Head": "कुटुंबप्रमुखाशी नाते",
    "Sex": "लिंग",
    "Age": "वय",
    "Aadhaar Seeded": "आधार जोडलेले",
    "e-KYC Status": "ई-केवायसी स्थिती",
    "Commodity": "वस्तू",
    "Monthly Allotment": "मासिक वाटप",
    "Issue Price": "वितरण दर",
    "Allotment Basis": "वाटपाचा आधार",
    "Total Monthly Grain": "एकूण मासिक धान्य",
    "Date & Time": "दिनांक व वेळ",
    "Allotment Month": "वाटपाचा महिना",
    "Commodity / Quantity": "वस्तू / प्रमाण",
    "Authentication Mode": "प्रमाणीकरण पद्धत",
    "Task": "काम",
    "Usually": "सहसा",
    "Last night": "काल रात्री",
    "Night job": "रात्रीचे काम",
    "What it does": "ते काय करते",
    "Learning": "शिकणे",
    "Last run": "शेवटची फेरी",
    "Last check": "शेवटची तपासणी",
    "Day": "दिवस",
    "Result": "निकाल",
    "Why": "का",
    "Job": "काम",
    "Feature": "वैशिष्ट्य",
    "Median": "मध्यक",
    "Spread": "फैलाव",
    "Observations": "निरीक्षणे",
    "Snapshot": "स्नॅपशॉट",
    "Taken at": "घेतल्याची वेळ",
    "Health": "आरोग्य",
    "Files": "फाइल्स",
    "Manifest hash": "मॅनिफेस्ट हॅश",
    "Signals": "संकेत",
    "Reasons": "कारणे",

    # --- form labels and buttons -----------------------------------------------
    "Ration card number": "शिधापत्रिका क्रमांक",
    "All Talukas": "सर्व तालुके",
    "All Schemes": "सर्व योजना",
    "All Statuses": "सर्व स्थिती",
    "Search": "शोधा",
    "Reset Filters": "निकष रीसेट करा",
    "Clear Filters": "निकष काढा",
    "Back to Search": "शोधाकडे परत",
    "Back to Ration Card Search": "शिधापत्रिका शोधाकडे परत",
    "Return to Ration Card Search": "शिधापत्रिका शोधाकडे परत जा",
    "Open Data Safety": "डेटा सुरक्षा उघडा",
    "Open Vault Console (Simulation)": "व्हॉल्ट कन्सोल उघडा (सराव)",
    "Supervisor authorisation PIN": "पर्यवेक्षक अधिकृतता PIN",
    "Restore records to office computer": "नोंदी कार्यालयीन संगणकावर पुनर्स्थापित करा",
    "Return to Incident Alert": "घटना इशाऱ्याकडे परत जा",
    "Acknowledge": "पोच द्या",
    "Run Full MVP Demo": "संपूर्ण MVP प्रात्यक्षिक चालवा",
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
