"""Synthetic call transcripts, one string per STT sentence. All names are invented and there are
no real phone, account, Aadhaar or PAN numbers. Spellings mimic STT output, mistakes included
("arest", "Aadhar", "AnyDisk", "batayiye", "acount")."""

SCAMS: dict[str, list[str]] = {
    "cbi_digital_arrest": [
        "Hello, kya main Ramesh Kulkarni ji se baat kar raha hoon?",
        "Main Inspector Vikram Rathore bol raha hoon, CBI Mumbai crime branch se.",
        "Aapke Aadhaar card se ek SIM nikla hai jo money laundering case mein use hua hai.",
        "आपके नाम पर अरेस्ट वारंट जारी हुआ है।",
        "Aap abhi se digital arest mein hain, video call par camera on rakhiye.",
        "यह बात किसी को मत बताइए, अपने परिवार को भी नहीं।",
        "Call mat kaatna, warna local police aapke ghar aa jayegi.",
        "Aapke bank acount ko verify karne ke liye saare paise RBI ke safe account mein transfer karne honge.",
        "Verification ke baad paisa refund ho jayega, chinta mat kijiye.",
    ],
    "customs_parcel_drugs": [
        "Namaskar, main FedEx courier se bol rahi hoon.",
        "Aapke naam se Taiwan bhejne wala ek parcel Mumbai customs ne pakda hai.",
        "Usme paanch passport, teen credit card aur do sau gram MDMA drugs mile hain.",
        "मैं आपका कॉल नारकोटिक्स डिपार्टमेंट को ट्रांसफर कर रही हूँ।",
        "Narcotics officer: Aapke khilaf FIR darj ho chuki hai aur aapka Aadhar drug trafficking se link hai.",
        "Skype par video call join kijiye, aapka statement record hoga.",
        "Jab tak investigation chal rahi hai, kisi se baat mat kijiye.",
        "Apne account ka balance verify karne ke liye poora amount RTGS se hamare verification account mein bhejiye.",
    ],
    "trai_sim_disconnection": [
        "Yeh call TRAI, Telecom Regulatory Authority of India ki taraf se hai.",
        "Aapka mobile number do ghante mein band kar diya jayega.",
        "आपके आधार से लिए गए दूसरे नंबर से गैरकानूनी विज्ञापन और हैरेसमेंट मैसेज भेजे गए हैं।",
        "Agar aap is bare mein jaankari chahte hain toh nau dabaiye.",
        "Main Sunil Mehra, TRAI se. Aapko Andheri police station se clearance certificate lena hoga.",
        "Main aapka call cyber crime police ko connect kar raha hoon.",
        "Aapke khilaf complaint register hai, aapka statement video call par liya jayega.",
        "Verification ke liye apna Aadhar number aur us par aaya OTP batayiye.",
    ],
    "bank_kyc_otp": [
        "Hello sir, main SBI head office se bol raha hoon, KYC department.",
        "Aapka KYC expire ho gaya hai, aaj raat tak update nahi kiya toh account block ho jayega.",
        "Aapke registered number par humne ek link bheja hai, usko open kijiye.",
        "अब आपके फ़ोन पर एक छह अंकों का ओटीपी आया होगा, वो बताइए।",
        "Sir jaldi kijiye, OTP sirf do minute valid hai.",
        "Apne debit card ke peeche wala CVV number bhi bataiye verification ke liye.",
        "Is call ke baare mein kisi ko bhi mat bataiye, ye bank ka internal process hai.",
    ],
    "electricity_remote_app": [
        "Namaste, main bijli vibhag se bol raha hoon.",
        "Aapka pichhle mahine ka bill update nahi hua hai, aaj raat saadhe nau baje aapki bijli kaat di jayegi.",
        "Turant electricity officer se baat kijiye, main unka assistant hoon.",
        "Bill update karne ke liye Play Store se AnyDisk Quick Support app download kariye.",
        "App kholkar jo nau digit ka code aa raha hai, wo mujhe bataiye.",
        "अब सिर्फ दस रुपये का पेमेंट कीजिए अपने डेबिट कार्ड से, बिल अपडेट हो जाएगा।",
        "Screen par jo dikh raha hai usko band mat kijiye, phone mat kaatiye.",
    ],
}

NORMALS: dict[str, list[str]] = {
    "bank_relationship_manager": [
        "Good morning Mr. Kapoor, main Ananya, HDFC Bank se aapki relationship manager.",
        "Aapki fixed deposit agle hafte mature ho rahi hai, isliye call kiya.",
        "Agar aap renew karna chahein toh branch aakar form sign kar dijiye, ya net banking se khud kar lijiye.",
        "Abhi senior citizen ke liye saadhe saat percent ka rate chal raha hai.",
        "Aapka KYC bhi agle mahine due hai, branch mein documents le aaiye.",
        "Aur ek zaroori baat, bank kabhi bhi phone par OTP ya PIN nahi maangta, kisi ko mat bataiye.",
        "Koi sawal ho toh aap mujhe isi number par call kar sakte hain, dhanyavaad.",
    ],
    "courier_directions": [
        "Hello, main Delhivery se delivery boy bol raha hoon, aapka parcel hai.",
        "Address mein Sector ikkees likha hai, par gali number samajh nahi aa raha.",
        "Mandir ke paas wali gali hai kya? Main abhi petrol pump ke saamne khada hoon.",
        "Pin code wahi hai na jo order mein likha hai?",
        "Theek hai, main paanch minute mein pahunch raha hoon.",
        "Order prepaid hai, bas delivery ke time OTP bata dena.",
    ],
    "family_grocery_money": [
        "Hello Mummy, main Riya bol rahi hoon.",
        "Ghar mein aata, daal aur sabzi khatam ho gayi hai.",
        "Mujhe grocery ke liye do hazaar rupaye bhej do na, Google Pay par.",
        "हाँ बेटा, अभी यूपीआई से भेज देती हूँ।",
        "Aur papa ko mat batana ki maine chips bhi mangwaye hain.",
        "Paise aa gaye, thank you Mummy, shaam ko milte hain.",
    ],
    "doctor_appointment": [
        "Namaste, main Sunrise Clinic se bol rahi hoon.",
        "Kal subah gyarah baje Doctor Meera Iyer ke saath aapka appointment hai.",
        "Kripya pandrah minute pehle aa jaiye aur purani reports saath laiye.",
        "Pehli baar aa rahe hain toh apna Aadhaar card bhi le aaiye registration ke liye.",
        "Agar time change karna ho toh isi number par call kar dijiye.",
        "Consultation fee clinic par hi cash ya UPI se de sakte hain.",
    ],
    "telecom_plan_offer": [
        "Hello sir, main Jio customer care se Rohit bol raha hoon.",
        "Aapka current plan teen din mein expire ho raha hai.",
        "Hamare paas teen sau unchaas rupaye ka naya plan hai, unlimited calls aur roz do GB data.",
        "Aap MyJio app se ya kisi bhi recharge shop se recharge kar sakte hain.",
        "Abhi recharge karne par pachaas rupaye ka cashback bhi milega.",
        "Kya main aapko plan details SMS kar doon?",
    ],
}
