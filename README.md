# Numerotunnistus

Windowsin paikallinen kilpailunumeroiden tunnistin. Nykyinen ohjelma on
`numerontunnistin_paikallinen.py`: se tunnistaa numerolappuja PaddleOCR:llä
MP4-tiedostosta, NDI-lähteestä tai RTSP/HTTP-videovirrasta. Paikallinen OCR
ei tarvitse Claudea eikä API-avainta. Tulokset ovat havaintoja, eivät
virallisia maaliintuloaikoja.

## Toiminnot

- Esikatselu sekä tunnistuksen aloitus ja pysäytys.
- Tunnistusalue ja kellon poissulkualue piirretään esikatseluun.
- Luottamus-, tekstikoko-, vahvistus- ja dominanssiehdot sekä kaksoishavaintojen esto.
- MP4:n ruutuaikaan perustuvat havainnot ja liikkeenseuranta.
- Live-vastaanotto erillisessä prosessissa, rajattu tuoreimman kuvan puskuri,
  hallittu uudelleenyhdistys ja seurantajaksojen erottaminen yhteyskatkossa.
- CSV, tarkistuskuvat, epävarmat havainnot ja päätösten perustelut.
- Live-kuvamäärät, OCR-kutsujen alku/loppu/kesto, näytenopeus, viive ja tracebackit.
- Täsmälliset OCR-syötekuvat, kaikkien raakatekstien loki ja syötteen uudelleenvertailu.
- JSON-asetusten lataus, tallennus ja viimeksi käytettyjen asetusten palautus.
- Toistettava parametrivertailu MP4-videon ja erillisen vertailutotuuden avulla.

## Windows-asennus

Käytä 64-bittistä Python 3.11:tä, jossa ovat Tkinter/Tcl/Tk ja venv.
Tällä koneella toimiva OCR-ympäristö on Python **3.11.17**.
Älä korvaa jo toimivaa `.venv`-ympäristöä: seuraavat asennuskomennot ovat
uudelle kloonille tai erilliselle asennuskansiolle.

```powershell
git clone https://github.com/POL1951/Numerotunnistus.git
cd Numerotunnistus
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install paddlepaddle-gpu==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
.\.venv\Scripts\python.exe -m pip install -r requirements-paikallinen-lock.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe numerontunnistin_paikallinen.py
```

Aktivointi ei ole välttämätön: käytä aina `.venv\Scripts\python.exe`-tulkkia.
Myös `kaynnista_paikallinen.ps1` käynnistää saman tulkin projektikansiosta.

Lukitustiedosto tallentaa nykyisen OCR-ympäristön kaikki 70 asennettua pakettia
täsmäversioina; se on tämän Windows/Python 3.11/GPU-ympäristön snapshot,
ei yleiskäyttöinen ratkaisu kaikille käyttöjärjestelmille. `requirements-paikallinen.txt`
sisältää pienemmän suorien OCR-riippuvuuksien listan, jonka transitiviiset
riippuvuudet eivät ole yhtä tarkasti lukittuja. Keskeiset versiot:

| Riippuvuus | Toimivassa ympäristössä |
|---|---|
| Python, OCR | 3.11.17, 64 bit |
| paddlepaddle-gpu | 3.2.2, CUDA 11.8 -jakelu |
| paddleocr | 3.2.0 |
| paddlex | 3.2.1 |
| opencv-contrib-python | 4.10.0.84 |
| numpy, OCR | 1.26.4 |
| pillow | 11.3.0 |
| Python, erillinen NDI-vastaanotin | 3.14.4, 64 bit |
| ndi-python | 6.3.2.4 |
| numpy, erillinen NDI-vastaanotin | 2.5.3 |

Pakettilukitus ei sisällä Pythonia, NVIDIA-ajuria tai NDI-ajoympäristöä.
Täysin uuden koneen asennusta ei ole vielä varmennettu tällä lukituksella.

## GPU, PaddleOCR ja paikalliset mallit

GPU vaatii yhteensopivan NVIDIA-näytönohjaimen ja CUDA 11.8 -jakelulle
sopivan ajurin. Tarkista jakelun laitevaatimukset
[PaddlePaddlen Windows-asennusohjeesta](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/windows-pip_en.html).
Ohjelman `auto` kokeilee oikeaa GPU-operaatiota ja käyttää tarvittaessa CPU:ta;
`gpu` vaatii toimivan GPU:n, `cpu` pakottaa CPU:n. GPU-paketti tukee myös
ohjelman CPU-valintaa. Erillistä CPU-only-pakettilukitusta ei ole varmennettu.

Ohjelma käyttää `PP-OCRv4_mobile_det`- ja `PP-OCRv4_mobile_rec`-malleja.
Ensimmäinen OCR-alustus verkkoyhteydellä hankkii puuttuvat mallit kirjaston
normaalilla mallilatauksella. Voit alustaa ne myös ilman videota:

```powershell
.\.venv\Scripts\python.exe -c "from numerontunnistin_paikallinen import PaddleEngine; PaddleEngine('auto', print)"
```

Mallihakemistot ovat projektin alla:

```text
.models/paddlex/official_models/PP-OCRv4_mobile_det/
.models/paddlex/official_models/PP-OCRv4_mobile_rec/
```

Jos ehjät mallit ovat jo koneella, kopioi molemmat kokonaiset hakemistot
yllä olevaan rakenteeseen. Säilytä mukana `inference.yml`, `inference.json`
ja `inference.pdiparams` sekä mallin muut tiedostot. Ohjelma käyttää olemassa
olevia paikallisia malleja eikä edellytä niiden uudelleenlatausta.
Kun mallit ja kirjastot ovat paikallisesti käytettävissä, OCR toimii offline.
Kirjastojen `PADDLE_HOME` ja `PADDLE_PDX_CACHE_HOME` oletukset ovat projektin
`.models`-kansiossa; valmiiksi asetetut ympäristömuuttujat voivat ohittaa nämä.
Käyttäjän tulee voida lukea malleja ja kirjoittaa käytettävään välimuistiin.
Mallit ja välimuistit eivät kuulu Gitiin.

## NDI-vaatimukset

NDI on valinnainen; sen puuttuminen ei estä MP4- tai verkkovideokäyttöä.
Vastaanottokirjasto on [ndi-python / NDIlib](https://github.com/buresu/ndi-python).
NDI-ajoympäristö ja työkalut saa [NDI Toolsista](https://ndi.video/tools/).
Tällä koneella vastaanotto toimii NDI 6 Toolsilla ja erillisellä Python 3.14.4:llä.
OCR pysyy Python 3.11:n `.venv`-ympäristössä.

Ohjelma etsii `NDIlib`-kirjastoa ensin käynnistävästä tulkista, sitten Windowsin
käyttäjäkohtaisesta Python-asennuksesta
`%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe`.
Jos käytät erillistä 3.14-asennusta, sen täytyy olla tässä ohjelman tukemassa
asennusrakenteessa. NDI-pakettien saatavuus riippuu Python-versiosta.
Asenna ne siihen ympäristöön, jossa on yhteensopiva Windows-wheel:

```powershell
py -3.14 -m pip install -r requirements-ndi.txt
py -3.14 -c "import NDIlib; print('NDIlib OK')"
```

Älä asenna Python 3.14:n NumPy-versiota OCR:n `.venv`-ympäristöön.
Jos vastaanottokirjasto puuttuu, ohjelma näyttää virheen.
Lähteen löytyminen edellyttää lähettävää NDI-ohjelmaa ja toimivaa
lähdelöytöä/verkkoyhteyttä; liikkuva esikatselu varmennetaan ennen OCR:ää.

## Käyttö

**MP4:** valitse lähteeksi `MP4-tiedosto`, avaa video ja tarkista esikatselu.
Aseta tunnistusalue ja mahdollinen kellon poissulkualue, sitten aloita tunnistus.
Video ja mallien alustus voivat olla ensimmäisellä kerralla hitaita.

**NDI:** valitse `NDI`, paina `Päivitä lähteet`, valitse löydetty lähde ja yhdistä.
Esimerkiksi tämän koneen lähettäjä on nimeltään `LOCALHOST (VM33_0176E)`;
esimerkkiasetukset eivät sido ohjelmaa tähän lähteeseen. Tarkista liikkuva
esikatselu, aloita/pysäytä tunnistus ja katkaise vastaanotto tarvittaessa.

**Verkkovideo:** valitse `Verkkovideo`, anna täydellinen RTSP/HTTP-videovirran
URL ja yhdistä. Pelkkä IP-osoite ei riitä. Osoitteen pitää palauttaa OpenCV:n
FFmpeg-vastaanoton tukema videovirta; tavallinen HTML-sivu ei yleensä ole virta.
Esimerkiksi `rtsp://camera.example/stream` on osoitteen muoto, ei valmis lähde.
Salasanoja sisältäviä osoitteita ei tulosteta ajolokeihin.

## Asetukset ja tulokset

[Asetusohje: ASETUKSET.md](ASETUKSET.md) selittää jokaisen kentän, tukikaavat,
vahvistukset, CSV-kirjauksen ja ongelmatilanteiden tutkimisen. Käyttöliittymän
**Ohje** avaa saman ohjeen; kenttien päällä näkyvät lyhyet työkaluvihjeet.

`Lataa asetukset` ja `Tallenna asetukset` käyttävät JSON-tiedostoja.
`examples/asetukset.example.json` sisältää kaikki nykyiset kentät ilman
polkuja, lähdetunnuksia tai salasanoja. Ladatut arvot näkyvät käyttöliittymässä
ja ovat käytössä seuraavalla ajolla. Myös parametrivertailun tuottama
`parhaat_asetukset.json` voidaan ladata. Kuvarajaukset ovat pikselikoordinaatteja
`[x1, y1, x2, y2]`; niiden täytyy mahtua valitun lähteen kuvaan.

Ajossa käytetyt asetukset tallentuvat `viimeksi_kaytetyt_asetukset.json`-tiedostoon
ja palautuvat seuraavalla käynnistyksellä. JSON-asetustiedosto voi sisältää
verkkovirran koko URL:n tunnuksineen: henkilökohtaiset asetukset jätetään Gitistä
pois, ja myös erikseen viedyt JSON-tiedostot on säilytettävä yksityisinä.

Tulokset tulevat `paikalliset_tulokset/<aikaleima>/`-kansioon:
`havainnot.csv`, `epavarmat.csv`, tarkistuskuvat ja JSONL-diagnostiikka.
CSV-kirjaus odottaa seurannan päättymistä. Live-seuranta päättyy nykyisen
katkorajan jälkeen myös ilman uusia OCR-todisteita, vaikka taustan optinen virtaus
jatkuisi. Käyttöliittymä näyttää CSV-määrän ja loki seurannan estävät ehdot.
Live-CSV:n `vastaanotto_kellonaika` ja `istunnon_aika_s` ovat vastaanottohetken
aikoja, eivät virallisia maaliintuloaikoja. Katkon yli havaintoja ei yhdistetä.

`ocr_raakatekstit.jsonl` sisältää kaikki OCR-tekstit ennen numerosuodatusta.
`ocr_syotteet/` tallentaa rajatusti täsmällisiä OCR-syötteitä ja saman ruudun
vastaanottokuvia. `ocr_syotevertailu.json` vertaa ensimmäisen numerollisen
syötteen PNG-uudelleenajoa yhteiseen MP4/live-OCR-toteutukseen.
`ocr_seurantaketju.jsonl` jäljittää havainnot seurantaan ja hyväksymisehtoihin.

## Parametrivertailu

Kopioi oma testivideo projektin juureen nimellä `video.mp4` ja sen
vertailutotuus nimellä `numerot.csv`. Molemmat jäävät versionhallinnan ulkopuolelle.
`examples/numerot.example.csv` näyttää tiedostomuodon; sen numerot ja ajat
ovat pelkkiä esimerkkejä. Videoita ei toimiteta repositoriossa.

CSV:ssä ei ole otsikkoriviä. Sarakkeet erotellaan puolipisteellä:
`numero;nakymisen_alku;nakymisen_loppu`.
Vertailutotuuden aikamuoto on **minuutit.sekunnit**:
`01.08 = 68 sekuntia`, `00.5 = 5 sekuntia`, `00.05 = 5 sekuntia`.
Pisteen jälkeinen osa on kokonaisia sekunteja (0–59), ei sekunnin desimaaleja.
Ohjelman tulos-CSV:n `*_aika_s`-arvot ovat puolestaan sekuntien desimaalilukuja.

```powershell
# Yksi kokonainen näyteväliskenaario ennen laajaa vertailua:
.\.venv\Scripts\python.exe -X utf8 parametrivertailu.py --first-experiment
# Koko olemassa oleva koesuunnitelma:
.\.venv\Scripts\python.exe -X utf8 parametrivertailu.py
```

Nykyinen koesuunnitelma arvioi 648 asetusyhdistelmää, käyttää kolmea
OCR-näyteväliä sekä saman kuvan SHA256-tunnisteeseen perustuvaa OCR-välimuistia.
Tulokset, välitulokset, `parhaat_asetukset.json` ja `LOPPURAPORTTI.md` syntyvät
`testiaineisto/parametrivertailu/`-kansioon. Vertailuohjelma on alun perin tehty
10 numeron aineistolle: osa raportin tekstistä käyttää tätä lukumäärää kiinteästi.
Arvioinnin yksityiskohtaiset JSON-tulokset perustuvat annettuun CSV:hen.
Parhaat asetukset ovat aineistoon sovitettuja, eivät yleispäteviä kamerarajoja.

## Testit ja lähdekoodi

```powershell
.\.venv\Scripts\python.exe -m unittest discover
# Oikea GPU/CPU-autovalinnalla ajettava OCR-testi, verkko estetty testissä:
.\.venv\Scripts\python.exe -X utf8 test_paikallinen.py --ocr --offline
```

Tekniset testit eivät tarvitse yksityisiä videoita tai ladattuja OCR-malleja.
Ne luovat itse tarvittavan synteettisen MP4:n; GUI-testit tarvitsevat Windowsin
työpöydän ja Tkinterin. Oikea OCR-testi tarvitsee paikalliset mallit.

| Tiedostot | Tehtävä |
|---|---|
| `numerontunnistin_paikallinen.py` | Tkinter-käyttöliittymä, asetukset, PaddleEngine ja MP4-ajo |
| `havaintoseuranta.py`, `seurannan_tallennus.py` | Seuranta, hyväksymisehdot, CSV ja tarkistuskuvat |
| `live_video.py`, `live_vastaanotin.py` | Vastaanottoprosessi, tuorein kuva, live-OCR ja diagnostiikka |
| `parametrivertailu.py` | Koesuunnitelma ja parametrien arviointi |
| `test_*.py` | Tekninen regressiotestistö |
| `diagnosoi_ocr.py`, `vertaa_ocr_syote.py` | Mallien ja tallennetun OCR-syötteen diagnostiikka |
| `varmista_live.py`, `varmista_ndi_ocr.py` | HTTP-/NDI-integraatiotestit erikseen käytettävillä lähteillä |

Integraatiotestit tarvitsevat käyttäjän omat videot tai löydettävän NDI-lähteen.
`varmista_live.py` käyttää historiallisia testiasetuksia, joten se ei ole
käyttäjän kamerakohtaisten rajojen hyväksymistesti.
Vanha Claude/API-ohjelma `numerontunnistin.py`, paikalliset selvitysraportit,
videot, OCR-mallit ja koetulokset eivät kuulu tähän paikalliseen OCR-julkaisuun.
Myös aiempien yksittäisten korjausvertailujen työskriptit jätetään pois;
nykyinen parametrivertailu ja sen tarvitsemat moduulit ovat mukana.

`repository-files.txt` luettelee paikalliseen commitiin tarkoitetut tiedostot.
`prepare_commit.ps1` tarkistaa Gitin ja etärepositorion luettavissa olevan tilan,
estää pois jätettävien tiedostojen päätymisen seurantaan ja luo vain paikallisen
commitin. Se tarvitsee Git for Windowsin sekä käyttäjän Git-author-asetukset.
Skripti ei puske eikä korvaa olemassa olevaa etärepositoriota. Jos etärepositoriota
ei voi lukea, paikallinen valmistelu on mahdollista, mutta ennen myöhempää pushia
on tarkistettava sen historia ja sovitettava paikallinen haara siihen.

Viimeisin tekninen varmennus: 42 testiä sekä MP4:n GPU/offline-OCR.
Oikeat aiemmin tallennetut NDI-aluekuvat on tunnistettu, mutta viimeisintä
seurannan päättymiskorjausta ei ole vielä varmennettu tuoreella live-NDI:llä
usealla lapulla. HTTP-liveputken tallennus ja uudelleenyhdistyminen on testattu.
