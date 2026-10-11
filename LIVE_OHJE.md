# Paikallisen numerontunnistimen livevideo

Käynnistä projektin `.venv`-ympäristössä:

```powershell
.\.venv\Scripts\python.exe numerontunnistin_paikallinen.py
```

## Lähteen valinta

- **MP4-tiedosto**: avaa video `Avaa MP4`-painikkeella. Esikatselu, haku ja koko tiedoston tunnistus toimivat kuten aiemmin.
- **NDI**: paina `Päivitä lähteet`, valitse löydetty lähde ja paina `Yhdistä`. Tavoitelähde on `LOCALHOST (VM33_0176E)`. Haku ja yhdistäminen toimivat taustalla. Jos listassa ei ole lähteitä, lähdettä ei havaittu; valmiiksi täytetty tavoitenimi ei ole osoitus löydetystä lähteestä.
- **Verkkovideo**: kirjoita täydellinen `rtsp://`, `rtsps://`, `http://` tai `https://`-videovirran URL ja paina `Yhdistä`. Pelkkä IP-osoite tai tavallinen verkkosivu ei tarkoita videovirtaa.

Varmista ensin esikatselukuva. Rajaa tunnistusalue ja kellon poissulkualue kuten MP4:ssä tai lataa ne JSON-asetuksista. Paina sitten `Aloita tunnistus`. `Pysäytä` pysäyttää OCR-ajon ja tallentaa keskeneräiset seurannat tarkistettaviksi; vastaanotto ja esikatselu voivat jatkua. `Katkaise` lopettaa vastaanoton ja pyytää myös mahdollisen OCR-ajon pysähtymistä. Esikatselun voi tauottaa erikseen tunnistuksen aikana.

Jos muutat lähteen nimeä tai URL:ää yhdistämisen jälkeen, yhdistä uudelleen ennen tunnistuksen aloittamista. Liian suurista rajauksista ilmoitetaan; niitä ei muuteta automaattisesti. Sovellus ei yhdistä lähteisiin automaattisesti käynnistyessään.

## Asetukset ja kirjaukset

Lähdetyyppi, NDI-lähteen nimi ja videovirran URL kuuluvat nyt samoihin JSON-asetuksiin kuin tunnistusasetukset. Aiemmat `parhaat_asetukset.json`-tiedostot toimivat edelleen ja saavat lähdetyypiksi MP4-tiedoston. Käytetyt asetukset palautetaan seuraavalla käynnistyksellä, mutta yhteys muodostetaan käyttäjän painikkeella.

URL tallennetaan asetustiedostoon syötetyssä muodossa. Ajolokeista ja ajon metatiedoista poistetaan URL:n käyttäjätunnus, salasana ja kyselyparametrit. URL välitetään vastaanottoprosessille stdin-putkessa, ei komentorivillä. Natiivin verkkovastaanottimen diagnostiikka ei päädy sovelluslokiin.

Live-ajon `havainnot.csv` ja `epavarmat.csv` sisältävät lisäkentät:

- `vastaanotto_kellonaika`: kyseisen ensimmäisen OCR-havainnon paikallinen vastaanottokellonaika aikavyöhykkeineen.
- `istunnon_aika_s`: saman havainnon aika yhteysistunnon alusta, mukaan lukien mahdolliset katkot ja mallialustus.

Nämä ovat havaintoaikoja, eivät virallisia maaliintuloaikoja. Vanhojen CSV-kenttien `videon_aika_s` ja muiden suhteellisten aikojen sisältö on live-ajossa istunnon suhteellista aikaa. Tarkistuskuvan oma aika on edelleen erillinen `kuvan_aika_s`, sillä paras kuva voi olla ensimmäistä havaintoa myöhempi.

Hyväksyttyjen ja epävarmojen havaintojen tiedot tallentuvat samoihin tuloskansioihin kuin MP4-ajossa. Hyväksytylle tallennetaan yksi paras JPEG-tarkistuskuva (laatu 90), epävarmalle seurantatapahtumalle enintään kolme kuvaa yhteensä. CSV:n kaikki vaihtoehdot säilyvät, vaikka osalle ei tallenneta kuvaa. Näyteloki kertoo vastaanottoajan ja yhteysjakson.

Normaalitilassa ei tallenneta livevideota eikä ylimääräisiä OCR-syötekuvia. Debug on oletuksena pois. Debug tallentaa käsitellyt OCR-näytekuvat PNG:nä enintään 256 MiB:n yhteiseen istuntobudjettiin (`debug` ja `ocr_syotteet`). Tekniset JSONL-lokit kiertävät kokorajalla 2 MiB × 4 osaa/loki; havainto-CSV:t eivät kierrä.

Ikkunan alareuna näyttää tuloskansion, istunnon koon, vapaan levytilan ja debug-rajan. Vapaasta tilasta varoitetaan alle 1 GiB:ssa, ja kuvien tallennus keskeytetään 256 MiB:n vararajalla tai kuvan kirjoitusvirheestä. Tunnistus ja CSV-tallennus jatkuvat niin kauan kuin kirjoittaminen onnistuu. Katso [tallennusohje ja mitattu tilantarve](TALLENNUS_OHJE.md).

## Vastaanotto ja katkot

Vastaanotto toimii omassa prosessissa, jota erillinen lukusäie tyhjentää jatkuvasti. Sovelluksessa säilytetään vain uusin vastaanottokuva. Hitaampi OCR ei kasvata kuvajonoa: seuraava käsiteltävä kuva on uusin saatavilla oleva. Esikatselu toimii Tk:n pääsäikeessä; OCR on omassa työntekijäsäikeessä.

Yhteyden tila, toteutunut OCR-näytenopeus ja vastaanotosta käsittelyn valmistumiseen kulunut viive näkyvät käyttöliittymässä. Esikatselun rivillä näkyy myös vastaanottokuvan ikä. OCR-nopeus on kuluvan tunnistusajon keskiarvo.

Katkon jälkeen uudelleenyhdistämisen odotus kasvaa 1 sekunnista enintään 8 sekuntiin. Verkkovastaanottimen avaustimeout on 5 s ja lukutimeout 2 s. NDI:n kuvaton vastaanotto katkaistaan 5 s jälkeen. Myös yli 2 s väli vastaanottokuvissa aloittaa uuden yhteysjakson, vaikka NDI-kirjasto palauttaisi yhteyden itse.

Katko tai kuvakoon muutos katkaisee seurantajaksot. Katkon aikana käynnissä olleen OCR-kutsun tulos hylätään, eikä havaintoja yhdistetä katkon yli. Keskeneräiset seurannat tallennetaan tarkistettaviksi. Seurantojen numerointi jatkuu ilman tunnisteiden uudelleenkäyttöä.

## NDI-riippuvuudet tällä koneella

Projektin Python 3.11 `.venv` ei sisällä `NDIlib`-moduulia. Koneella on jo Python 3.14:n `ndi-python` 6.3.2.4 ja NDI 6 Tools. Sovellus käyttää löydettyä olemassa olevaa Python 3.14 -asennusta NDI-vastaanottoprosessiin, koska sen `cp314`-laajennusta ei voi tuoda Python 3.11:een. OCR pysyy projektin `.venv`-ympäristössä.

NDI käyttää alkuperäisen ohjelman `find_create_v2`, `recv_create_v3`, BGRX/BGRA- ja `recv_capture_v2`-ratkaisua. Kuvadata kopioidaan ennen NDI-kuvapuskurin vapauttamista; audio ja metadata vapautetaan. Alkuperäistä Claude-ohjelmaa ei muutettu.

Jos vastaanottokirjastoa ei löydy, sovellus näyttää puuttuvan riippuvuuden. Uusia paketteja tai NDI Tools -asennuksia ei tehty tässä muutoksessa.

Testitulokset ja testaamatta jääneet lähteet: [LIVE_RAPORTTI.md](LIVE_RAPORTTI.md).

## OCR:n etenemisen tarkistus

Käyttöliittymän diagnostiikkarivi näyttää vastaanotettujen kuvien määrän,
OCR:lle annetut ja valmistuneet kuvat sekä työntekijäsäikeen vaiheen.
Ensimmäisen OCR-kutsun alku, loppu ja kesto näkyvät omalla rivillään ja lokissa,
vaikka yhtään numeroa ei löytyisi. Käynnissä olevan kutsun kulunut aika kasvaa
ennen sen valmistumista. Virheet näkyvät kokonaisina tracebackeina lokissa.

Kuvan ikä mitataan valmiin kuvan saapumisesta pääprosessiin samalla
monotonisella kellolla, jolla käyttöliittymä laskee iän. Tarkempi diagnoosi ja
testirajaukset: [NDI_DIAGNOSTIIKKARAPORTTI.md](NDI_DIAGNOSTIIKKARAPORTTI.md).
