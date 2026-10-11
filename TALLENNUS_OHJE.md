# Kilpailukäytön tallennus

Paikallisen ohjelman MP4-, NDI- ja verkkovideoajot käyttävät samaa rajattua tallennuskäytäntöä. Tunnistus- ja hyväksymisehdot säilyvät ennallaan. Käynnistä ohjelma uudelleen koodipäivityksen jälkeen.

## Normaalitila

- Kaikki päättyneiden seurantojen hyväksytyt ja epävarmat havaintorivit säilyvät `havainnot.csv`- ja `epavarmat.csv`-tiedostoissa. Niitä ei kierrätetä, tyhjennetä tai poisteta automaattisesti.
- Hyväksytystä havainnosta tallennetaan yksi paras tarkistuskuva. Parhaaksi valitaan suurimman OCR-luottamuksen kuva, tasatilanteessa ensimmäinen.
- Epävarmasta seurantatapahtumasta tallennetaan enintään kolme kuvaa yhteensä. Valitaan vaihtoehtojen parhaat kuvat luottamuksen mukaan. Jos tapahtumassa on hyväksytty numero ja epävarmoja vaihtoehtoja, hyväksytyn kuva kuuluu samaan kolmen kuvan enimmäismäärään.
- Kuvat ovat alkuperäisen kokoisia, merkittyjä JPEG-kuvia laadulla 90. Erillisiä rajauskuvia ei tehdä normaalitilassa. JPEG-koodaus koskee vain tallennettavaa kopiota, eikä muuta OCR-syötettä.
- Kuvakandidaatit säilyvät muistissa tapahtuman päättymiseen asti. Kuvia ei kirjoiteta levylle jokaisella lukukerralla. CSV:n `kuvan_aika_s` vastaa kyseisen vaihtoehdon parhaan kuvan aikaa.
- Jos vaihtoehto ei mahdu kuvarajaan tai kuvatallennus on keskeytetty, sen CSV-rivin `tarkistuskuva` on tyhjä. Havaintorivi ja muut tiedot säilyvät silti.
- Livevideota ei tallenneta automaattisesti. Normaalitilassa ei tallenneta OCR-syötekuvia, vastaanottokuvien sarjaa eikä kaikkia näyteruutuja.

## Debug ja tekniset lokit

Debug on oletuksena pois. Päällä se tallentaa OCR-näytekuvat häviöttöminä PNG-tiedostoina, kunnes istunnon yhteinen **256 MiB:n kuvabudjetti** täyttyy. Liveajon `ocr_syotteet`- ja `debug`-kansiot käyttävät samaa budjettia. Rajan saavuttaminen näkyy käyttöliittymässä ja lokissa; tunnistus ja normaalit tarkistuskuvat jatkuvat. Raja tarkistetaan ennen seuraavan kuvan kirjoitusta, joten liian suuri seuraava kuva jätetään tallentamatta.

Tekniset JSONL-lokit kierrätetään: yksi osa enintään **2 MiB**, aktiivinen osa ja **kolme varmuuskopio-osaa** (`.1`, `.2`, `.3`). Vanhin osa korvataan vasta saman uuden lokin kierrätyksessä. Yli 2 MiB:n yksittäinen tekninen merkintä ohitetaan ilmoituksen kanssa. Lokien vanhat osat eivät ole kilpailun pysyvä havaintoarkisto; pysyvät havaintotiedot ovat CSV:ssä.

MP4-ajossa teknisten lokien yhteisraja on 32 MiB (neljä lokia). NDI- ja verkkovideoajossa se on 56 MiB (seitsemän lokia). Lisäksi mallialustuksen ja työntekijän yhteinen `live_diagnostiikka/tyontekija.jsonl` kiertää enintään 8 MiB:n kokonaiskokoon. Yhteisloki ei sisälly yksittäisen tuloskansion kokoon. Pienet `ajo.json`, `yhteenveto.json` ja mahdollinen `virhe.txt` ovat ajokohtaisia.

Vanhoihin ajokansioihin ja niiden kuviin tai lokeihin ei kohdisteta tätä jälkikäteen. CSV:t ja normaalit JPEG-tarkistuskuvat kasvavat havaintomäärän mukaan, joten koko kilpailun levykoko ei ole kiinteästi rajattu.

## Levytila ja virhetilanteet

Ikkunan alareuna näyttää tuloskansion, istunnon tiedostojen koon, levyn vapaan tilan ja debug-rajan. Tiedot päivitetään käsittelyn yhteydessä enintään viiden sekunnin välein sekä istunnon alussa ja lopussa. Pitkän OCR-kutsun aikana viimeisin mittaus jää näkyviin.

Alle **1 GiB** vapaasta tilasta annetaan varoitus. Jos seuraavan kuvan tallennus veisi vapaan tilan alle **256 MiB:n vararajan**, kaikkien kuvien tallennus keskeytetään istunnon loppuajaksi. Kuvan kirjoitusvirhe keskeyttää kuvat samalla tavalla. Selvä `KUVATALLENNUS KESKEYTETTY` -ilmoitus jää levytilariville. Tunnistus ja CSV-tallennus jatkuvat; jo tallennetut kuvat jäävät levylle. Tilaa vapautettaessa uusi istunto palauttaa kuvien tallennuksen.

Teknisen lokin kirjoitusvirhe ilmoitetaan ja kyseinen loki keskeytetään. CSV:n kirjoitusvirhe näkyy lokissa ja tunnistusvirheilmoituksessa; ajo ei ilmoita onnistuneensa, jos havaintojen kirjoittaminen epäonnistuu. Vararaja ei takaa kirjoituskelpoisuutta esimerkiksi oikeusvirheen, toisen ohjelman levykäytön tai laitevian aikana.

`Vie lista CSV:ksi` vie käyttöliittymän hyväksytyt numerot ja ajat erilliseen tiedostoon. Automaattiset yksityiskohtaiset CSV:t säilyvät tuloskansiossa. Pysäyttäminen jättää listan ja tulostiedostot talteen, uusi istunto aloittaa uuden listan.

## Tilantarve

120 sekunnin 1920×1080-testivideon tallennus oli 17,05 MiB: 8 hyväksyttyä havaintoa, 48 epävarmaa CSV-riviä ja 30 epävarmoja vaihtoehtoja sisältävää tapahtumaa. Samalla havaintotiheydellä kuuden tunnin arvio on noin **3,0 GiB normaalitilassa**. Mittaus käytti aiempia GPU-OCR-tuloksia, joiden syötekuvien SHA256 tarkistettiin; se ei ole nopeusmittaus tai kattava kilpailuolosuhteiden varmennus. Varaudu enemmän epävarmoja tapahtumia tai suurempia kuvia tuottavaa kilpailua varten suurempaan tilaan. Debug lisää enintään 256 MiB istuntoa kohti. Uusi istunto aloittaa uuden debug-budjetin.
