# Numerotunnistimen asetukset

Tämä ohje kuvaa nykyisen `numerontunnistin_paikallinen.py`-ohjelman,
`havaintoseuranta.py`-seurannan, `seurannan_tallennus.py`-tallennuksen ja
`live_video.py`-livepolun toimintaa. Asetukset eivät mittaa maalilinjan
ylitystä: CSV:n ajat ovat OCR-havaintoon ja vastaanottoon liittyviä aikoja.

Vie hiiri asetuskentän päälle nähdäksesi lyhyen selitteen. **Ohje** avaa
tämän tiedoston ohjelman omaan vieritettävään ohjeikkunaan ilman verkkoyhteyttä.
Säädä yksi asia kerrallaan ja tarkista ensin tallennettu kuva ja päätöksen
perusteet. Asetusten muuttaminen ei korjaa kuvaa, jossa numeroa ei ole.

## Neljä eri vaihetta

| Vaihe | Mitä se tarkoittaa | Mistä tarkistetaan |
|---|---|---|
| 1. OCR:n raakaluenta | PaddleOCR:n teksti, luottamus ja nelikulmainen tekstipolygoni ennen ohjelman numerosuodatusta. Myös sanat ja virhetulkinnat kuuluvat tähän. | Livessä `ocr_raakatekstit.jsonl` ja rajatusti `ocr_syotteet/*_ocr.png`. MP4:ssä tallennetun/debug-syötteen erillinen OCR-tarkistus. |
| 2. Seurannan ehdokas | Numeroksi tulkittu OCR-teksti on liitetty paikalliseen seurantaan. Sillä ei vielä välttämättä ole tarpeeksi kelvollisia vahvistuksia. | `raakahavainnot.jsonl`, liveketjun `ocr_seurantaketju.jsonl`, seurantatunnus ja tarkistuskuva. |
| 3. Hyväksytty havainto | Päättyneen seurannan numero täyttää kaikki soveltuvat hyväksymisehdot eikä tallennuksen kaksoisesto estä sitä. | `havainnot.csv` ja `seurannat.jsonl`: `hyvaksytty_numero`. |
| 4. Tarkistettavaksi jäänyt havainto | Seurannan numero tai vaihtoehto ei pääse hyväksyttyyn CSV:hen. Syynä voi olla laatu, vähäinen ruututuki, ristiriita, keskeytys, kaksoisesto tai vahvempi vaihtoehto. | `epavarmat.csv`, `seurannat.jsonl`: `syyt` ja `paatoksen_perusteet`. |

Pelkkä raakateksti ei siis ole hyväksytty havainto. Aktiivisen seurannan
`hyvaksyttavissa`-numero liveketjussa on väliaikainen arvio: myöhemmät
vaihtoehdot voivat vielä muuttaa päätöstä. Tarkistettavaksi jäänyt havainto
ei tarkoita automaattisesti väärää OCR-tekstiä.

Raakatekstistä poistetaan välilyönnit ja muut whitespace-merkit. Jäljelle
pitää jäädä 1–8 ASCII-numeroa ja luvun pitää olla suurempi kuin nolla.
`00123` muuttuu numeroksi `123`, myös `12 3` muuttuu `123`:ksi.
`123A`, `1O`, `12.3` ja `0` eivät kelpaa. Ohjelma ei arvaa O:ta nollaksi
tai I:tä ykköseksi. Numeron pituus ei ratkaise vaihtoehtojen voittajaa.

## Lähde, alueet ja laite

### Lähdetyyppi (`source_type`)

- **Käyttöliittymä:** Lähdetyyppi.
- **Vaihe ja arvot:** vastaanoton valinta: `MP4-tiedosto`, `NDI` tai `Verkkovideo`.
  Ei yksikköä eikä suurennettavaa/pienennettävää lukua.
- **Esimerkki:** valitse MP4 tallenteen analyysiin; NDI kameran lähetykseen.
- **Yhteisvaikutus:** määrää aikaleimat, vastaanoton ja näytevälin käytännön
  merkityksen. Lähdetyypin vaihto katkaisee nykyisen livevastaanoton.
  Tarkista lähteen kuvan mitat ja rajaukset ennen tunnistusta.

### Löydettyjen NDI-lähteiden valintalista (`ndi_source`)

- **Käyttöliittymä:** Päivitä lähteet -painikkeen vieressä oleva valintalista.
- **Vaihe ja arvot:** vastaanotto yhdistää täsmälleen valitun nimiseen löydettyyn
  lähteeseen. NDI-yhdistämiseen tarvitaan lähde; tyhjä arvo ei riitä.
  Ei yksikköä tai numeerista suurenemissuuntaa.
- **Esimerkki:** `LOCALHOST (VM33_0176E)` on tämän koneen lähettäjän nimi,
  ei kaikkien koneiden oletettava lähde.
- **Yhteisvaikutus:** edellyttää `NDI`-lähdetyyppiä ja NDIlib-vastaanottokirjastoa.
  Päivitä lähteet, Yhdistä ja tarkista liikkuva esikatselu ennen OCR:ää.
  OCR-rajojen muuttaminen ei auta puuttuvaan NDI-lähteeseen.

### RTSP/HTTP-videovirran URL (`stream_url`)

- **Käyttöliittymä:** RTSP/HTTP-videovirran URL.
- **Vaihe ja arvot:** verkkovastaanoton osoite; hyväksytyt URL-skeemat ovat
  `rtsp`, `rtsps`, `http` ja `https`. Tarvitaan palvelinnimi/IP osana URL:ia
  ja kelvollinen portti, jos se annetaan. Pelkkä IP ei kelpaa.
  Syntaktisesti kelvollinen osoite ei takaa toimivaa videovirtaa.
- **Esimerkki:** `rtsp://camera.example/stream` osoittaa muodon; oikea polku
  riippuu kamerasta. Numeron suurentaminen/pienentäminen ei sovellu URL:iin.
- **Yhteisvaikutus:** käytössä vain Verkkovideo-lähteelle. Virran resoluutio,
  pakkaus ja verkko vaikuttavat kuvan laatuun ja nopeuteen. URL:n tunnuksia
  ei tulosteta ajolokiin, mutta tallennettu asetus-JSON voi sisältää koko
  osoitteen salasanoineen. Älä julkaise henkilökohtaista asetustiedostoa.

### Rajaa tunnistusalue (keltainen) (`roi`)

- **Käyttöliittymä:** Rajaa tunnistusalue (keltainen); Koko kuva poistaa rajauksen.
- **Vaihe:** alkuperäisestä kuvasta leikataan tämä alue ennen OCR:ää.
  Muuta kuvaa ei anneta OCR:lle. OCR-polygonit siirretään takaisin koko
  kuvan koordinaatteihin lisäämällä rajauksen vasemman yläkulman sijainti.
- **Arvot:** `null` = koko kuva; JSON:ssa `[x1,y1,x2,y2]` kokonaisia alkuperäisen
  kuvan pikseleitä. `0 ≤ x1 < x2 ≤ leveys`, `0 ≤ y1 < y2 ≤ korkeus`.
  Hiirellä piirretty esikatselualue muunnetaan alkuperäisen kuvan koordinaatteihin.
- **Suurentaminen/pienentäminen:** laajempi alue kattaa useampia juoksijoita
  mutta sisältää enemmän taustaa. Pienempi voi nopeuttaa ja auttaa OCR:ää,
  mutta ulkopuolelle tai reunalle jäävä lappu voi kadota tai katketa.
- **Esimerkki:** 1920×1080-kuvassa `[200,150,1700,1000]` rajaa pois reunat.
- **Yhteisvaikutus:** poissulku peitetään tämän alueen sisällä.
  Korkeusraja pysyy alkuperäisen kuvan pikseleissä; alueen rajaaminen ei
  itsessään suurenna numeron mitattua korkeutta. Eri resoluution lähde voi
  tehdä tallennetusta rajauksesta kelvottoman. Seurannan liikkeenkäsittely
  käyttää koko kuvaa, eikä ROI yksin päätä aktiivista MP4-seurantaa.

### Rajaa kellon poissulkualue (punainen) (`exclusion`)

- **Käyttöliittymä:** Rajaa kellon poissulkualue (punainen);
  Poista poissulkualue poistaa sen.
- **Vaihe:** alue peitetään valkoisella ennen OCR:ää. Seurannan ryhmittely
  hylkää myös numeron, jonka akselisuuntainen polygonin rajauslaatikko leikkaa
  poissulkua positiivisella pinta-alalla. Alueelta ei kylvetä optisen virtauksen
  seurantapisteitä. Se ei ole pelkkä kuvan päälle piirretty punainen laatikko.
- **Arvot:** `null` tai `[x1,y1,x2,y2]`, samat pikseli- ja rajausehdot kuin ROI:lla.
- **Suurentaminen/pienentäminen:** suurempi peittää enemmän kellotekstiä mutta
  voi samalla poistaa oikeita lappuja; pienempi jättää enemmän kuvaa käyttöön
  mutta voi päästää kellon numerot ehdokkaiksi.
- **Esimerkki:** `[0,0,270,112]` peittää vasemman yläkulman aikaleiman vain
  kuvalähteessä, jossa kelloteksti sijaitsee siinä.
- **Yhteisvaikutus:** tarkista leikkaus ROI:n ja oikeiden numerolappujen kanssa.
  OCR- tai kokorajan laskeminen ei palauta peitettyä kuvaa.

### Laite (`device`)

- **Käyttöliittymä:** Laite; toteutunut laite näkyy erikseen Tunnistuslaite-rivillä.
- **Vaihe ja arvot:** PaddleOCR:n alustus: `auto`, `cpu`, `gpu`.
  Ei numeerista suurenemissuuntaa. `auto` kokeilee GPU:ta oikealla laskuoperaatiolla
  ja voi käyttää CPU:ta; `cpu` käyttää CPU:ta; `gpu` vaatii toimivan GPU:n.
- **Esimerkki:** käytä `auto` ja tarkista lokista `gpu:0`. GPU:n puuttuessa
  pakotettu `gpu` aiheuttaa virheen, ei hiljaista CPU-ajoa.
- **Yhteisvaikutus:** vaikuttaa käsittelyaikaan ja livekuvassa toteutuneeseen
  näytenopeuteen. Ei muuta hyväksymisrajoja. Ensimmäinen OCR-kutsu voi olla
  myöhempiä hitaampi; sen vuoksi nopeutta ei arvioida vain alustushetkestä.

## Näytteenotto ja yhden havainnon kelpoisuus

### Näyteväli (s) (`interval`)

- **Vaihe:** valitsee OCR:lle tarjottavien ruutujen tavoitevälin.
- **Yksikkö ja arvot:** sekuntia, äärellinen luku `> 0`. Ei kiinteää ylärajaa.
- **Suurempi:** harvempi OCR ja yleensä vähemmän laskentaa sekä vahvistuksia.
  **Pienempi:** enemmän mahdollisia vahvistuksia ja laskentaa; livessä ei
  kuitenkaan voi ylittää vastaanoton tai OCR:n todellista nopeutta.
- **Esimerkki:** `0.1` tarkoittaa noin 10 näytettä videosekunnissa MP4:ssä,
  jos videon FPS riittää. Se ei lupaa 10 valmistuvaa OCR-kutsua sekunnissa livessä.
- **Yhteisvaikutus:** Vahvistusruutuja ja Vahvistuksen aikaikkuna pitää voida
  täyttää lapun näkyessä. Katkoraja ei saa perustua oletettuun nopeuteen,
  jos toteutunut liveväli onkin huomattavasti suurempi.

### OCR-raja (0–1) (`confidence`)

- **Vaihe:** rajaa yksittäiset numerohavainnot kelvollisiksi vahvistuksiksi
  seurannan päätöksessä. Se ei ole PaddleOCR:n raakatekstien tulostusraja:
  mallin `text_rec_score_thresh` on koodissa 0, ja raakatulos voi näkyä
  ehdokkaana/tarkistuskuvassa, vaikka se jää käyttäjän OCR-rajan alle.
- **Yksikkö ja arvot:** OCR-luottamus, äärellinen luku `0 ≤ arvo ≤ 1`.
  Suurempi arvo tarkoittaa korkeampaa vaadittua luottamusta, ei virheprosenttia.
- **Suurempi:** karsii heikkoja havaintoja mutta voi jättää oikean lapun
  ilman vahvistuksia. **Pienempi:** lisää kelvollisia havaintoja ja samalla
  virhetulkintojen sekä kilpailevien vaihtoehtojen mahdollisuutta.
- **Esimerkki:** rajalla `0.85` luottamus `0.84` ei kelpaa, `0.85` kelpaa,
  jos koko- ja liitoslaatuvaatimuksetkin täyttyvät.
- **Yhteisvaikutus:** vaikuttaa myös tukiosuuteen, tukisuhteeseen, keskiarvoihin
  ja poikkeamien ruutumäärään, koska niissä käytetään kelvollisia havaintoja.
  Yksittäinen OCR-raja ja Keski-OCR ovat eri ehtoja.

### Numerorivin väh. korkeus (px) (`minimum_text_height`)

- **Vaihe:** yhden numerohavainnon kelpoisuus seurannan päätöksessä.
- **Yksikkö ja arvot:** alkuperäisen MP4-/vastaanottokuvan pikseleitä,
  äärellinen luku `≥ 0`.
- **Mittaus:** `min(|p0−p3|, |p1−p2|)`, eli OCR-nelikulmion kahden sivureunan
  lyhyempi pituus. Kallistus huomioidaan. Tämä ei ole akselisuuntaisen
  laatikon korkeus, koko numerolapun korkeus eikä esikatselun ruutupikselimäärä.
  OCR-syötettä leikataan, mutta ohjelma ei muuta sen mittakaavaa ennen
  `recognize`-kutsua. Mallin sisäinen kuvan skaalaus ei ole tämän rajan yksikkö;
  käytössä ovat palautetun polygonin syötekuvan koordinaatit. Liikkeenseuranta
  voi käyttää enintään 960 pikselin levyistä apukuvaa, mutta se ei määritä
  numeron korkeusrajan mittakaavaa.
- **Suurempi:** sulkee pieniä/kaukaisia numeroita pois. **Pienempi:** päästää
  niitä mukaan, myös pieniä taustan numerotekstejä.
- **Esimerkki:** 24 px korkea OCR-polygoni ei vahvista havaintoa rajalla 28 px.
- **Yhteisvaikutus:** resoluution, kameran etäisyyden ja rajauksen vaihtaminen
  muuttaa tilannetta. Rajan laskeminen ei auta, jos OCR ei löydä polygonia lainkaan.

## Vahvistukset ja seurannan kesto

### Vahvistusruutuja (väh. 2) (`confirmation_count`)

- **Vaihe:** vahvimman numeron moniruutuvahvistus ennen hyväksyntää.
- **Yksikkö ja arvot:** erilliset OCR-ruudut, kokonaisluku `≥ 2`.
- **Suurempi:** vaatii enemmän toistettavaa näyttöä; lyhyt näkyminen voi jäädä
  epävarmaksi. **Pienempi:** hyväksyntä on mahdollinen vähemmillä ruuduilla,
  mutta toistuvan virhetulkinnan torjunta heikkenee.
- **Esimerkki:** arvolla 4 tarvitaan neljä saman numeron kelvollista eri ruutua
  saman todistejakson sisällä ja aikaikkunaan mahtuen.
- **Yhteisvaikutus:** näyteväli, live-nopeus, aikaikkuna, OCR-raja, korkeusraja
  ja epävarman liitoksen katkaisu määräävät, syntyykö neljä kelvollista ruutua.

### Vahvistuksen aikaikkuna (s) (`confirmation_window`)

- **Vaihe:** saman numeron kelvolliset havaintoajat järjestetään ja niiden yli
  liu'utetaan aikaikkunaa. Etsitään ensimmäinen ikkuna, jossa ruututuki riittää.
  Ikkunan alku ei lukkiudu seurannan ensimmäiseen havaintoon.
- **Yksikkö ja arvot:** sekuntia, äärellinen luku `> 0`.
- **Suurempi:** sallii ajallisesti hajanaisemmat vahvistukset. **Pienempi:**
  vaatii tiheämpää näyttöä, mikä voi estää hitaassa liveajossa hyväksynnän.
- **Esimerkki:** ajat 10.0, 10.4, 10.8 ja 11.2 s mahtuvat 2 s ikkunaan.
  Ajat 10, 11, 12 ja 13 s eivät kaikki mahdu 2 s ikkunaan.
  Rajan tasan täyttävä aikaero sallitaan (koodissa lisäksi 1e−9 s toleranssi).
- **Yhteisvaikutus:** kyse on videon/vastaanoton havaintoajoista, ei OCR-kutsujen
  valmistumisajoista. Aikaikkuna koskee vahvistusta; dominanssin tuki ja
  keskiarvot lasketaan koko saman todistejakson kelvollisista havainnoista.

### Seurannan katkon sieto (s) (`track_gap`)

- **Vaihe:** seurannan päättäminen ja siten lopullisen päätöksen/CSV-kirjauksen ajankohta.
- **Yksikkö ja arvot:** sekuntia, äärellinen luku `> 0`.
- **MP4:** seuranta päättyy kuvan ulkopuolelle tai kun viimeisestä hyväksytystä
  visuaalisesta seurannasta on kulunut enemmän kuin tämä raja. Optinen virtaus
  voi jatkaa visuaalista seurantaa myös ilman uutta OCR-lukua.
- **Live:** edellisten lisäksi valmistuneen käsitellyn näytteen havaintoajan
  ja viimeisen seurantaan liitetyn numeron OCR-havaintoajan ero päättää
  seurannan, jos se ylittää rajan. Tähän kelloon kelpaa liitetty numerohavainto
  myös OCR-/kokorajan alapuolelta; kyse ei ole vain vahvistuskelpoisista ruuduista.
  Tarkistus tehdään OCR-käsittelyn jälkeen, eikä tyhjä vastaanotto itsessään
  käynnistä erillistä tarkkaa kahden sekunnin ajastinta.
- **Suurempi:** sietää pidempiä peittymisiä mutta voi pitkittää kirjauksen
  odotusta. **Pienempi:** päättää jakson nopeammin, mutta voi pilkkoa saman
  lapun useaan seurantaan ja vähentää ruututukea.
- **Esimerkki:** livessä viimeinen liitetty OCR-havainto on 20 s, seuraavan
  tyhjän OCR-näytteen aika 22.2 s ja katkoraja 2 s: jakso päättyy.
- **Yhteisvaikutus:** live-nopeus, näyteväli, vahvistukset ja saman numeron esto.
  Yhteyskatko ja resoluution muutos katkaisevat livejakson tästä asetuksesta
  riippumatta; havaintoja ei yhdistetä yhteyskatkon yli.

## Vahvimman vaihtoehdon ehdot

### Hyväksy vahvin vaihtoehto (`dominance_enabled`)

- **Vaihe ja arvot:** seurannan numeroristiriidan ratkaisu; valintaruutu,
  JSON:ssa `true` tai `false`.
- **Päällä:** kahdesta tai useammasta kelvollisesta numerovaihtoehdosta voidaan
  hyväksyä vahvin vain kaikkien seuraavien dominanssiehtojen täyttyessä.
  **Pois:** kaksi kelvollista vaihtoehtoa johtaa syyhyn `ristiriitaiset_numerot`.
- **Esimerkki:** 123 näkyy useissa hyvissä ruuduissa ja 128 yhdessä: päälläolo
  mahdollistaa 123:n hyväksynnän, mutta ei takaa sitä.
- **Yhteisvaikutus:** jos kelvollisia numerovaihtoehtoja on vain yksi,
  Tukiosuus, Tukisuhde, Keski-OCR, Liitoslaatu ja Poikkeaman enimm. ruudut
  eivät tule lisäehdoiksi. Yhden numeronkin täytyy täyttää muut ehdot.

### Tukiosuus (`dominance_share`)

- **Vaihe:** kahden tai useamman kelvollisen numerovaihtoehdon dominanssipäätös.
- **Yksikkö ja arvot:** osuus, äärellinen luku `0 < arvo ≤ 1` (0.65 = 65 %).
- **Suurempi:** vaatii sekä painotetun tuen että ruututuen selvempää enemmistöä.
  **Pienempi:** sallii suuremman osuuden kilpailevia tulkintoja.
- **Esimerkki:** painotettu osuus 0.72 mutta ruutuosuus 0.60 ei riitä rajalla
  0.65: molempien on oltava vähintään 0.65.
- **Yhteisvaikutus:** kelpoisuusrajat muuttavat laskettavia ruutuja.
  Tukisuhde ja vaihtoehtojen ruutumäärä tarkistetaan tämän lisäksi.

### Tukisuhde (`dominance_ratio`)

- **Vaihe:** vahvimman painotetun tuen vertailu toiseksi vahvimpaan.
- **Yksikkö ja arvot:** suhdeluku, äärellinen luku `> 1`.
- **Suurempi:** vaatii selvemmän eron. **Pienempi:** sallii tasaisemman kilpailun.
- **Esimerkki:** tuki 9 ja toiseksi vahvimman tuki 3 antaa suhteeksi 3,
  joka täyttää rajan 3. Suhde ei vertaa vahvinta kaikkien muiden yhteissummaan.
- **Yhteisvaikutus:** luottamus ja liitoslaatu painottavat tukea; Tukiosuus
  tarkistaa erikseen suhteen kaikkien vaihtoehtojen yhteistukeen.

### Keski-OCR (`dominance_confidence`)

- **Vaihe:** vahvimman numeron kaikkien kelvollisten ruutujen OCR-luottamusten
  tavallinen aritmeettinen keskiarvo dominanssitilanteessa.
- **Yksikkö ja arvot:** luottamus, äärellinen luku `0 < arvo ≤ 1`.
  Suurempi tarkoittaa vaadittua parempaa luottamusta.
- **Suurempi:** karsii keskimäärin heikommat voittajat. **Pienempi:** hyväksyy
  niitä helpommin, jos muutkin ehdot täyttyvät.
- **Esimerkki:** 0.90, 0.80 ja 0.70 antavat keskiarvon 0.80, jos kaikki
  kolme ovat yksittäisen OCR-rajan ja muiden kelpoisuusrajojen sisällä.
- **Yhteisvaikutus:** jos yksittäinen OCR-raja on 0.85, kaikki kelvolliset
  ruudut ovat jo vähintään 0.85, joten Keski-OCR 0.80 ei kiristä niiden ehtoa.
  Keskiarvo ei käytä vain valittua vahvistusikkunaa. CSV:n `ocr_luottamus`
  on puolestaan valitun vahvistusjoukon keskiarvo ja voi siksi poiketa tästä.

### Liitoslaatu (`dominance_track_quality`)

- **Vaihe:** vahvimman numeron kelvollisten havaintojen seurantaliitoslaadun
  aritmeettisen keskiarvon vähimmäisarvo dominanssitilanteessa.
- **Yksikkö ja arvot:** laatu 0–1; säädettävä alaraja on äärellinen
  `0 < arvo ≤ 1`. **Suurempi laatu on parempi.**
- **Suurempi raja:** vaatii varmemmat liitokset. **Pienempi:** sallii
  epävarmempia liitoksia, mutta ei poista kiinteää 0.4:n ruutukohtaista kelpoisuusrajaa.
- **Esimerkki:** laadut 1.0, 0.8 ja 0.6 antavat keskiarvon 0.8,
  joka täyttää rajan 0.7.
- **Yhteisvaikutus:** vaikuttaa sekä tukipainoon että keskiarvorajaan.
  Laatu ei ole OCR-luottamus eikä liitoskustannus: kustannuksessa pienempi
  on parempi, mutta siitä johdetussa laadussa suurempi on parempi.
  Katkaistun jakson epävarman aloitusruudun laatu 0 ei koskaan kelpaa
  vahvistukseksi, vaikka tämä säädettävä keskiarvoraja olisi hyvin pieni.

### Poikkeaman enimm. ruudut (`dominance_max_alternative_frames`)

- **Vaihe:** dominanssipäätös; lasketaan kelvolliset ruudut **kutakin muuta
  numeroa kohti erikseen**, koko todistejaksolta. Ei kaikkien poikkeamien summaa.
- **Yksikkö ja arvot:** ruutuja/vaihtoehtoinen numero, kokonaisluku `≥ 0`.
- **Suurempi:** sallii enemmän toistoja kustakin kilpailevasta numerosta.
  **Pienempi:** rajoittaa niitä tiukemmin. Arvo 0 estää usean kelvollisen
  numeron tilanteen hyväksynnän tämän ehdon perusteella.
- **Esimerkki:** vahvin 123, numero 128 yhdessä ruudussa ja 129 yhdessä
  ruudussa: raja 1 täyttyy kummallekin, vaikka poikkeamaruutujen summa on 2.
  Jos 128 esiintyy kahdessa kelvollisessa ruudussa, raja 1 ei täyty.
- **Yhteisvaikutus:** heikot tai pienet ruudut eivät ole tässä laskennassa
  mukana. Tukiosuus ja Tukisuhde voivat silti estää esimerkin hyväksynnän.

## Tarkat laskentakaavat

Olkoon `E_n` numeron n kelvollisten havaintojen joukko saman seurannan
todistejaksolta. Havainto kelpaa, kun:

1. koko teksti läpäisi numerosuodatuksen ja päätyi seurantaan;
2. `OCR-luottamus ≥ OCR-raja`;
3. `tekstikorkeus ≥ Numerorivin väh. korkeus`;
4. `liitoslaatu ≥ 0.4` (kiinteä ruutukohtainen raja).

Lisäksi ryhmittely karsii ei-äärelliset luottamukset, käytännössä tyhjät
laatikot (leveys/korkeus enintään 1 px) ja poissulkua leikkaavat laatikot.
Samalla numerolla on saman seurannan ruututunnusta kohti enintään yksi
havainto: useasta samasta numerosta säilytetään luottamukseltaan paras.
Optisen virtauksen väliin seuratut ruudut eivät ole OCR-vahvistuksia.

Merkitään havainnon OCR-luottamusta `c_i` ja liitoslaatua `q_i`:

```text
N_n = |E_n|
W_n = Σ (c_i × q_i), i ∈ E_n
b = suurimman W_n:n numerovaihtoehto
s = toiseksi suurimman W_n:n numerovaihtoehto

painotettu tukiosuus = W_b / Σ W_n
ruutuosuus           = N_b / Σ N_n
tukisuhde            = W_b / max(W_s, 0.000000001)
keski-OCR            = Σ c_i / N_b, i ∈ E_b
keski-liitoslaatu    = Σ q_i / N_b, i ∈ E_b
```

Joukkoon summataan kaikki **kelvolliset** numerovaihtoehdot, ei pelkkiä
raakaluentoja eikä OCR-rajan alle jääneitä vaihtoehtoja. Keskiarvot eivät
ole painotettuja keskiarvoja. Tukipaino on luottamuksen ja liitoslaadun tulo.
Tukiosuus-asetus vaatii **molempien osuuksien** täyttävän saman rajan.
Kaikki nämä dominanssiehdot on täytettävä yhdessä; yhden läpäisy ei riitä.

Laskenta käyttää koko todistejaksoa eikä vain Vahvistuksen aikaikkunaa.
Jos samassa ruudussa on saman seurannan kaksi eri numerovaihtoehtoa,
se ruutu voi osallistua kummankin vaihtoehdon `N_n`:ään. Nimittäjä ei siis
ole kaikkien vaihtoehtojen yhteisten ruututunnusten uniikkimäärä.

Esimerkiksi 123:lla on 10 kelvollista ruutua, jokaisella `c=0.90`, `q=0.80`;
128:lla yksi ruutu arvoilla `c=0.90`, `q=1.0`:

```text
W_123 = 10 × 0.90 × 0.80 = 7.2
W_128 = 0.90
painotettu osuus = 7.2 / 8.1 ≈ 0.889
ruutuosuus = 10 / 11 ≈ 0.909
tukisuhde = 7.2 / 0.90 = 8
keski-OCR = 0.90; keski-liitoslaatu = 0.80
```

Rajat 0.65, 3, 0.8, 0.7 ja poikkeamaraja 1 täyttyvät, mutta numeron
hyväksyntä vaatii lisäksi riittävän ruututuen aikaikkunassa, valmiin
seurannan, turvaestojen puuttumisen ja tallennuksen kaksoisestojen läpäisyn.

## Liitoslaatu ja epävarman liitoksen katkaisu

Seurantaa yhdistetään sijainnin, koon, liikkeen ja vaatetuksen värituntomerkin
avulla. Numerotekstiä ei käytetä liitoskustannuksen laskemiseen.
Ensin sijainti-, koko- ja värirajat karsivat mahdollisia liitoksia. Jäljelle
jääneen liitoksen kustannus on:

```text
kustannus = keskusten_etäisyys / sijaintiportti
           + 0.25 × (1 − laatikoiden_IoU)
           + 0.5 × värietäisyys
liitoslaatu = max(0, 1 − kustannus / 2)
```

IoU kuvaa laatikoiden päällekkäisyyttä; suurempi on parempi. Värietäisyydessä
pienempi on parempi. Sijaintiportti riippuu laatikoiden koosta, viimeisestä
OCR-havainnosta kuluneesta ajasta ja liikkeestä. Asetuskentän Liitoslaatu
muuttaminen ei muuta näitä geometrisia portteja tai kustannuskaavaa.

Tavallisen uuden seurannan ensimmäisen liitoksen laatu on 1.0.
Jos kilpailevan, vielä vapaana olevan liitoksen kustannus eroaa valitusta
alle 0.12, liitos on epäselvä. Tällöin:

1. kaikki tilanteeseen liittyvät vanhat seurannat päätetään;
2. vanhoja havaintoja ei siirretä uusiin seurantoihin;
3. uusiin jaksoihin tallennetaan mahdolliset edeltäjä-ID:t;
4. epävarman aloitusruudun liitoslaatu on 0, joten se ei vahvista numeroa;
5. myöhempien varmasti liitettyjen ruutujen pitää vahvistaa uusi jakso itsenäisesti.

Vanha valmis jakso voi silti tulla hyväksytyksi omilla aiemmilla todisteillaan.
Katkaisu ei automaattisesti hylkää kaikkia vanhoja todisteita. Jos sama numero
on jo kirjattu mahdollisessa edeltäjäjaksossa, uusi jakso ei saa kirjata sitä
uudelleen pelkän epävarman liitosrajan yli. Lokit ovat `liitokset.jsonl` ja
`seurannat.jsonl`: `todistejakson_rajat`, `mahdolliset_edeltajat`.

## Saman numeron kaksoisesto ja debug-kuvat

### Saman numeron esto eri seurannoille (s; 0=pois) (`duplicate_seconds`)

- **Vaihe:** tallennus tarkistaa tämän vasta, kun seurannan päätös muuten
  hyväksyisi numeron. Ei yhdistä eri seurantoja eikä kerää niiden vahvistuksia yhteen.
- **Yksikkö ja arvot:** sekuntia, äärellinen luku `≥ 0`.
- **Tarkka ehto:** uuden seurannan `last_visual` − saman numeron viimeksi
  hyväksytyn seurannan `last_visual` on vähintään asetettu aika. Lyhyempi ero
  tuottaa syyn `uuden_seurannan_saman_numeron_aikaesto`. Kyse ei ole CSV-rivin
  ensimmäisten OCR-aikojen erosta eikä tietokoneen tiedostonkirjoitushetkien erosta.
- **Suurempi:** estää saman numeron uusia kirjauksia pidempään, mutta voi estää
  aidon uuden esiintymisen. **Pienempi:** sallii uudet jaksot nopeammin ja voi
  päästää seurannan pilkkoutumisesta tulevia kaksoiskirjauksia.
- **Esimerkki:** edellisen seurannan loppuaika 30 s, uuden 36 s, esto 10 s:
  uutta numeroa ei kirjata hyväksyttyihin. Ero 10 s täyttää rajan.
- **Yhteisvaikutus:** Katkon sieto ja epävarmat liitokset voivat jakaa havainnot
  eri seurantoihin. Arvo 0 poistaa tavallisen aikaeston etenevillä aikaleimoilla,
  mutta **ei** poista mahdollista edeltäjäjakson saman numeron kirjausestoa
  (`aiemman_todistejakson_saman_numeron_kirjaus`). Estot ovat ajokohtaisia;
  uusi ajo ei lue edellisen ajon CSV:tä kaksoiseston muistiksi.

### Debug: kaikki OCR-näytekuvat (`debug_frames`)

- **Vaihe ja arvot:** tallennus; valintaruutu, JSON:ssa `true`/`false`.
- **Päällä:** tallentaa debug-kansioon käsiteltyjen OCR-näytteiden kuvia.
  MP4 tallentaa sekä merkityn koko kuvan että rajatun/peitetyn OCR-syötteen;
  live tallentaa koko vastaanottoruudun. Livepolun rajattu `ocr_syotteet`
  -tallennus säilyttää erikseen täsmällisiä syötteitä debug-valinnasta riippumatta.
- **Pois:** nämä kaikkien näytteiden debug-kuvat jäävät tallentamatta;
  tarkistuskuvat, epävarmat havainnot ja live-raakatulosloki säilyvät.
- **Esimerkki:** kytke päälle lyhyeen MP4-diagnoosiin ja vertaa `alue_ruutu...png`
  -kuvasta, peittyykö lappu kellon poissulkuun.
- **Yhteisvaikutus:** pienellä näytevälillä syntyy paljon kuvia. Levytilan
  käyttö ja kirjoitusviive kasvavat ja voivat hidastaa live-OCR:ää.
  Valinta ei muuta mitään hyväksymisrajaa. Se ei tallenna kaikkia vastaanoton
  väliin jääviä kuvia eikä jatkuvaa videota.

## Milloin hyväksytään ja milloin kirjoitetaan?

Valmis seuranta käsitellään `TrackRecorder.finalize`-funktiossa. Numeron
on läpäistävä kelpoisuus, tarvittaessa dominanssi, ruututuki aikaikkunassa ja
turvaestot. Keskeytetty seuranta saa syyn `keskeytetty_seuranta` ja jää tarkistukseen.
Sen jälkeen tarkistetaan edeltäjäesto ja eri seurantojen saman numeron aikaesto.
Vasta näiden jälkeen lisätään rivi `havainnot.csv`:hen ja päivitetään CSV-laskuri.

MP4:ssä seuranta päättyy ulosmenoon, visuaalisen seurannan katkoon tai videon
normaaliin loppuun. Pysäytys jättää vielä aktiiviset seurannat keskeytetyiksi.
Livessä myös OCR-todisteen katkoraja voi päättää jakson. Pysäytys, yhteyskatko,
resoluution muutos ja käsittelyvirhe päättävät jäljellä olevat aktiiviset jaksot
keskeytettyinä; jo kirjattuja rivejä ei poisteta.

Hyväksytyn CSV:n `videon_aika_s` on ensimmäisen riittävän vahvistusjoukon
ensimmäisen havainnon aika. `vahvistettu_aika_s` on tämän joukon viimeisen
havainnon aika. `ensi_ocr_aika_s` voi olla aikaisempi, koska se sisältää
numeron ensimmäisen liitetyn havainnon myös ennen vahvistuskelpoisuutta.
`kirjaus_videon_aika_s` on seurannan viimeinen visuaalinen havaintoaika,
ei käyttöjärjestelmän CSV-kirjoitushetki. Tarkistuskuva on parhaalla OCR-
luottamuksella valittu todistekuva, joten sen aika voi poiketa rivin havaintoajasta.
Live-CSV:hen lisätyt vastaanoton kellonaika ja istunnon aika kohdistuvat
rivin havaintoon, eivät viralliseen maaliintuloon.

## MP4:n ja livekuvan näyteväli

MP4 etenee tallenteen ruutuindeksien mukaan. OCR-ruututavoite muodostetaan
näytevälistä ja FPS:stä; samaa ruutua ei toisteta ja pienin väli on yksi
videoruutu. Hidas OCR pidentää ajon seinäkelloaikaa, mutta se ei hyppää
tuoreimpaan tallenteen kuvaan. Aktiivisten seurantojen liikettä seurataan
myös OCR-näytteiden välisillä videoruuduilla.

Livevastaanotto jatkuu erikseen OCR:n aikana. Käsittely saa tuoreimman
vastaanottoruudun, ja vanhat väliruudut ohitetaan. Näyteväli on vähimmäinen
aikavälitavoite käytettyjen vastaanottohetkien välillä, ei valmistuvien
OCR-kutsujen nopeuslupaus. OCR, liikkeenseuranta, tallennus, mallin ensimmäinen
alustus ja lähteen FPS rajoittavat todellista nopeutta. Esimerkiksi asetus
0.1 s ja OCR-keston/kokonaiskäsittelyn vaatima 0.2 s eivät tuota 10 näytettä/s.
Seurannan liikekäsittelykin näkee käsittelijän poimimat ruudut, ei välttämättä
kaikkia NDI:stä vastaanotettuja ruutuja.

Katso toteutuneet ajat lokista. Neljän vahvistuksen saaminen vaatii vähintään
kolme näytteiden välistä aikaeroa; näin `Vahvistusruutuja = 4` ja tasainen
0.5 s toteutunut väli tarvitsevat vähintään 1.5 s näkyvyyttä. Tätäkään
ei taata, jos jokin ruutu jää OCR-/koko-/liitoslaaturajan alle.

## Asetustiedostot ja testattu esimerkki

**Lataa asetukset** tuo JSON:n arvot näkyviin käyttöliittymään seuraavaa ajoa
varten; **Tallenna asetukset** vie nykyiset arvot JSON:iin. Asetusten lataus
katkaisee aiemman livevastaanoton. Ajossa käytetyt asetukset tallentuvat
`viimeksi_kaytetyt_asetukset.json`:iin ja palautuvat seuraavassa käynnistyksessä.
Näitä tiedostoja ja kameran tunnuksia ei julkaista Gitissä.

Parametrivertailun `testiaineisto/parametrivertailu/parhaat_asetukset.json`
on **testattu esimerkki yhdelle MP4-aineistolle**, ei kaikille kameroille ja
kilpailuille sopiva yleisasetus. Tässä vertailussa löytyi 9/10 totuusnumeroa
ilman vääriä hyväksyntöjä tai kaksoiskirjauksia. Tulos ei ole uusi livekameran
validointi eikä osoita, että samat rajat toimivat muissa olosuhteissa.

Esimerkin arvot ovat näyteväli 0.1 s, OCR-raja 0.85, korkeus 28 px,
4 vahvistusruutua / 2 s, katkon sieto 2 s ja saman numeron esto 10 s.
Dominanssi on päällä: tukiosuus 0.65, tukisuhde 3, Keski-OCR 0.8,
Liitoslaatu 0.7 ja enintään yksi kelvollinen ruutu **kutakin** muuta numeroa kohti.
Sen poissulku `[0,0,270,112]` on juuri testivideon kellolle.

Versionoitu `examples/asetukset.example.json` sisältää kaikki nykyiset kentät,
mutta jättää lähdenimen, URL:n ja kamerakohtaiset rajaukset tyhjiksi.
Koodin oletukset ja käynnistyksessä palautetut viime asetukset voivat poiketa
testatusta esimerkistä: tarkista käyttöliittymä ja ajon `ajo.json`.

## Ongelmatilanteet: tarkista loki ennen säätämistä

| Ongelma | Tarkista ensin kuva ja loki | Säätäminen vasta löydöksen perusteella |
|---|---|---|
| Numero näkyy mutta sitä ei löydy | Vertaa saman ruututunnuksen vastaanottokuvaa ja `ocr_syotteet/*_ocr.png`:ää. Onko lappu ROI:ssa, peitetty tai liian sumea? Katso `ocr_raakatekstit.jsonl`: teksti, luottamus, polygoni, resoluutio ja eheystarkistus. Oliko teksti esim. `123A`, joka ei läpäise numerosuodatusta? MP4:ssä käytä debug-syötettä ja erillistä OCR-tarkistusta. | Korjaa ensin lähde, valaisu, tarkennus ja rajaus. Jos numeroa ei ole raakatekstissä, seurannan tukirajojen laskeminen ei auta. Jos raakateksti on oikea, siirry ketjun suodatuksen/liitoksen tarkistukseen. |
| Oikea numero jää epävarmaksi | Katso `epavarmat.csv`:n `syy` sekä `seurannat.jsonl` → `paatoksen_perusteet`, `hylatyt_ruudut`, `estavat_ehdot`, kelvolliset ajat ja vaihtoehdot. Oliko luottamus liian pieni, korkeus alle rajan, ruututuki esim. 3 < 4, vaihtoehtoja liikaa tai seuranta keskeytetty? Katso myös `liitokset.jsonl`. | Muuta vain todistetusti estävää asetusta; arvioi samalla virhehyväksynnän riski. Vahvistusikkunan laajennus ei poista liitoskatkaisua, eikä dominanssi auta ilman kelvollisia ruutuja. |
| Numero kirjautuu kahdesti | Tarkista hyväksyttyjen rivien `seuranta_id`, ajat, `kirjaus_videon_aika_s`, `ajo.json`:n estoarvo sekä `mahdolliset_edeltajat` ja todistejakson rajat. Tulivatko rivit eri ajoista, pilkkoutuiko seuranta ja oliko loppuaikojen ero vähintään aikaesto? Jo hyväksytyt rivit ovat eri asia kuin epävarmojen vaihtoehtorivit. | Tarvittaessa pidennä aikaestoa tai tutki seurannan pilkkoutumisen syy. Katkorajan suurentaminen voi hidastaa kirjausta; aikaesto ei yhdistä seurantoja eikä toimi eri ajojen välillä. |
| Vierekkäiset juoksijat sekoittuvat | Tarkista tarkistuskuvien laatikot/seuranta-ID:t, `liitokset.jsonl`:n kustannukset, `liitoskustannusten_ero_alle_rajan`, katkaistut jaksot ja nollalaatuinen aloitusruutu. Tarkista `liitoslaatu` ja vahvat numerovaihtoehdot samassa jaksossa. | Paranna kuvakulmaa, erottuvuutta ja aluevalintaa. Älä laske Liitoslaatua tai salli lisää poikkeamia vain saadaksesi rivin: ne voivat helpottaa sekoittuneen jakson hyväksyntää. Numeroteksti ei ole seurannan yhdistämiskriteeri. |
| Livekuva toimii mutta tunnistus on hidas | Vertaa vastaanotettujen, OCR:lle annettujen ja valmistuneiden kuvien laskureita. Katso toteutunut näytenopeus, viive, aktiivisen kutsun kesto, ensimmäisen kutsun alku/loppu sekä todellinen laite (`gpu:0`/CPU). Tarkista `ocr_diagnostiikka.jsonl`, tracebackit, debug-kuvien määrä ja kerran tehtävän syötevertailun viesti. Esikatselun FPS ei ole OCR:n FPS. | Varmista ensin GPU tai rajaa turhaa kuva-alaa; kytke tarpeeton debug-tallennus pois. Suurempi näyteväli vähentää kuormaa mutta myös vahvistuksia. Pienempi väli ei nopeuta yksittäistä OCR-kutsua. Sovita vahvistusikkuna mitattuun nopeuteen, älä peitä jumittuvaa kutsua rajoja laskemalla. |

Liveketjun kaikki raakatekstit tallentuvat myös tyhjällä tuloksella.
Raakatekstit ja niiden syötekuvat näkyvät käyttöliittymän lokissa rajatusti;
tarkista täydellinen JSONL-tiedosto, jos numeron yksittäinen lukukerta ei
näy loki-ikkunassa. MP4:n `raakahavainnot.jsonl` sisältää seurantaan päätyneet
numerot, ei kaikkia PaddleOCR:n sanatekstejä. Katso aina kyseisen ajon kansiota.

Laskennan lähteet: `numeric_text`, `Settings.validate`, `process_video` ja
käyttöliittymän kentät (`numerontunnistin_paikallinen.py`);
`text_height`, `Track.candidates`, `Track.decision`, `BibTracker.update`
(`havaintoseuranta.py`); `TrackRecorder.finalize` (`seurannan_tallennus.py`);
`retire_live_without_ocr` ja `process_live` (`live_video.py`).
