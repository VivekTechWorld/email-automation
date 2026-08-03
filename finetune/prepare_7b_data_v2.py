import json
import os

# Source text (The core knowledge we want to inject)
# We will create variations in both English and Finnish

scenarios = [
    {
        "id": "wordpress_edit",
        "en": {
            "questions": [
                "I can't find where I can edit the front page text in WordPress.",
                "How do I change the homepage text?",
                "Where is the front page editor?",
                "I want to update the text on my main landing page."
            ],
            "response": "Hi,\nThe front page content can usually be edited in the Pages section of WordPress.\nDo the following:\n1. Log in to your WordPress admin\n2. Select “Pages” from the left menu\n3. Open “Front Page”\n4. Make the necessary changes\n5. Save with the “Update” button\nIf the site uses Elementor or another page builder, the content is opened with the “Edit with Elementor” button.\nAdditional instructions: https://wordpressohjeet.artcloud.fi"
        },
        "fi": {
            "questions": [
                "En löydä mistä voin muokata etusivun tekstiä WordPressissä.",
                "Miten muokkaan etusivun sisältöä?",
                "Mistä löytyy etusivun muokkaus?",
                "Haluan vaihtaa tekstiä kotisivullani."
            ],
            "response": "Hei,\nEtusivun sisältöä voidaan yleensä muokata WordPressin Sivut-osiosta.\nToimi seuraavasti:\n1. Kirjaudu WordPress-hallintaan\n2. Valitse vasemmasta valikosta “Sivut”\n3. Avaa “Etusivu”\n4. Tee tarvittavat muutokset\n5. Tallenna “Päivitä”-painikkeella\nMikäli sivusto käyttää Elementor- tai muuta sivunrakentajaa, sisältö avataan “Muokkaa Elementorilla” -painikkeesta.\nLisäohjeet: https://wordpressohjeet.artcloud.fi"
        }
    },
    {
        "id": "dns_propagation",
        "en": {
            "questions": [
                "I changed the nameservers but the website still doesn’t open.",
                "My site is down after DNS update.",
                "Why isn't my domain working after I switched name servers?",
                "I updated my DNS settings yesterday but nothing is happening."
            ],
            "response": "Hi,\nIt can normally take a few hours to 24–48 hours for nameserver changes to be updated to the internet.\nPlease also check:\n• that the correct name servers have been set for the domain\n• that the DNS records can be found in the new environment\n• that there is no old cache in the browser\nYou can also try the site via a mobile network or on another device.\nIf the problem persists after 48 hours, we will check the situation technically."
        },
        "fi": {
            "questions": [
                "Vaihdoin nimipalvelimet mutta verkkosivu ei vieläkään avaudu.",
                "Sivusto on alhaalla DNS-päivityksen jälkeen.",
                "Miksi domain ei toimi vaikka vaihdoin nimipalvelimet?",
                "Päivitin DNS-asetukset eilen, mutta mitään ei tapahdu."
            ],
            "response": "Hei,\nNimipalvelinmuutosten päivittyminen internetiin voi kestää normaalisti muutamasta tunnista jopa 24–48 tuntiin.\nTarkistathan lisäksi:\n• että verkkotunnukselle on asetettu oikeat nimipalvelimet\n• että DNS-tietueet löytyvät uudesta ympäristöstä\n• ettei selaimessa ole vanhaa välimuistia\nVoit myös kokeilla sivustoa mobiiliverkon kautta tai toisella laitteella.\nMikäli ongelma jatkuu 48 tunnin jälkeen, tarkistamme tilanteen teknisesti."
        }
    },
    {
        "id": "email_creation",
        "en": {
            "questions": [
                "How do I create a new email address?",
                "I need a new email account.",
                "Where can I add a new email for my employee?",
                "Steps to set up a new mailbox?"
            ],
            "response": "Hi,\nYou can create a new email account via cPanel.\nFollow these steps:\n1. Log in to the customer portal\n2. Open the web hosting service\n3. Go to cPanel\n4. Select “Email Accounts”\n5. Create a new email address and password\nWe recommend using a strong password.\nAdditional instructions: https://wordpressohjeet.artcloud.fi"
        },
        "fi": {
            "questions": [
                "Miten teen uuden sähköpostiosoitteen?",
                "Tarvitsen uuden sähköpostilaatikon.",
                "Mistä voin lisätä sähköpostin työntekijälle?",
                "Ohjeet uuden postilaatikon luontiin?"
            ],
            "response": "Hei,\nUuden sähköpostilaatikon voit luoda cPanelin kautta.\nToimi seuraavasti:\n1. Kirjaudu asiakasportaaliin\n2. Avaa webhotellipalvelu\n3. Siirry cPaneliin\n4. Valitse “Email Accounts”\n5. Luo uusi sähköpostiosoite ja salasana\nSuosittelemme käyttämään vahvaa salasanaa.\nLisäohjeet: https://wordpressohjeet.artcloud.fi"
        }
    },
    {
        "id": "portal_login",
        "en": {
            "questions": [
                "I can’t log in to the portal even though my password is correct.",
                "Login failed in customer portal.",
                "Portal is rejecting my password.",
                "Why can't I get into my account?"
            ],
            "response": "Hi,\nWe recommend first:\n• clearing your browser cache\n• trying private browsing mode\n• checking that no old password has been saved in the browser\nIf you are still unable to log in, you can use the “Forgot your password” function.\nIf the problem persists, we will check your account technically."
        },
        "fi": {
            "questions": [
                "En pääse kirjautumaan portaaliin vaikka salasana on oikein.",
                "Kirjautuminen epäonnistui asiakasportaalissa.",
                "Portaali hylkää salasanani.",
                "Miksi en pääse kirjautumaan tililleni?"
            ],
            "response": "Hei,\nSuosittelemme ensin:\n• tyhjentämään selaimen välimuistin\n• kokeilemaan yksityistä selaustilaa\n• tarkistamaan ettei selaimeen ole tallentunut vanhaa salasanaa\nMikäli kirjautuminen ei tämän jälkeen onnistu, voit käyttää “Unohtuiko salasana” -toimintoa.\nJos ongelma jatkuu edelleen, tarkistamme käyttäjätilin teknisesti."
        }
    },
    {
        "id": "site_down",
        "en": {
            "questions": [
                "The website is showing an error message and is not opening at all.",
                "My site is broken. Showing error.",
                "Database error on my website.",
                "Emergency! My site is down!"
            ],
            "response": "Hi,\nThis appears to be a technical problem.\nFor the review, we need:\n• domain name\n• text of any error message\n• information about whether the problem is occurring for all users\nTechnical maintenance will check the server environment and the situation as quickly as possible.\nIf it is a wider service problem, we will inform you separately."
        },
        "fi": {
            "questions": [
                "Sivusto näyttää virheilmoitusta eikä avaudu ollenkaan.",
                "Sivustoni on rikki. Näkyy virheilmoitus.",
                "Tietokantavirhe verkkosivullani.",
                "Hätätilanne! Sivusto on alhaalla!"
            ],
            "response": "Hei,\nKyseessä vaikuttaa olevan tekninen häiriötilanne.\nTarvitsemme tarkistusta varten:\n• verkkotunnuksen\n• mahdollisen virheilmoituksen tekstin\n• tiedon siitä tapahtuuko ongelma kaikilla käyttäjillä\nTekninen ylläpito tarkistaa palvelinympäristön ja tilanteen mahdollisimman nopeasti.\nMikäli kyseessä on laajempi palveluhäiriö, tiedotamme siitä erikseen."
        }
    }
]

system_prompt = (
    "You are a professional customer support agent.\n"
    "Analyze this customer email and respond with ONLY valid JSON.\n\n"
    "JSON format:\n"
    "{\n"
    "  \"category\": \"support\",\n"
    "  \"severity\": \"normal\",\n"
    "  \"confidence\": 5,\n"
    "  \"needs_context\": false,\n"
    "  \"response\": \"<your full email reply>\"\n"
    "}\n\n"
    "Strict Rule: NEVER use placeholders like [Your Name]. Always sign off as: Support Team"
)

training_data = []

for item in scenarios:
    # Add English variations
    for q in item["en"]["questions"]:
        training_data.append({
            "instruction": system_prompt,
            "input": f"Customer Email:\nSubject: Help\nBody: {q}",
            "output": json.dumps({
                "category": "support",
                "severity": "normal",
                "confidence": 5,
                "needs_context": False,
                "response": item["en"]["response"]
            })
        })
    
    # Add Finnish variations
    for q in item["fi"]["questions"]:
        training_data.append({
            "instruction": system_prompt,
            "input": f"Customer Email:\nSubject: Apua\nBody: {q}",
            "output": json.dumps({
                "category": "support",
                "severity": "normal",
                "confidence": 5,
                "needs_context": False,
                "response": item["fi"]["response"]
            })
        })

# Output file
output_file = "data/training/7b_kb_v2.jsonl"
os.makedirs("data/training", exist_ok=True)

with open(output_file, "w", encoding="utf-8") as f:
    for entry in training_data:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

print(f"Created {len(training_data)} training pairs in {output_file}")
