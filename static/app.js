// vis/skjul formularer, bekræft sletning og hent produktoplysninger fra et link

document.addEventListener("click", (hændelse) => {
    const vis = hændelse.target.closest("[data-vis]");
    if (vis) {
        const felt = document.getElementById(vis.dataset.vis);
        if (felt) {
            felt.classList.remove("skjult");
            const første = felt.querySelector("input, textarea");
            if (første) første.focus();
        }
    }

    const skjul = hændelse.target.closest("[data-skjul]");
    if (skjul) {
        const felt = document.getElementById(skjul.dataset.skjul);
        if (felt) felt.classList.add("skjult");
    }

    const kopiér = hændelse.target.closest("[data-kopiér]");
    if (kopiér) {
        const felt = document.getElementById(kopiér.dataset.kopiér);
        if (felt) {
            felt.select();
            felt.setSelectionRange(0, felt.value.length);
            kopiér_tekst(felt.value);
        }
    }

    const kopiérTekst = hændelse.target.closest("[data-kopiér-tekst]");
    if (kopiérTekst) {
        kopiér_tekst(kopiérTekst.dataset.kopiérTekst);
    }
});

// kopiér et link til udklipsholderen

async function kopiér_tekst(tekst) {
    const status = document.getElementById("kopi-status");
    const skriv = (besked, klasse) => {
        if (status) {
            status.textContent = besked;
            status.className = "status " + klasse;
        }
    };

    try {
        await navigator.clipboard.writeText(tekst);
        skriv("Linket er kopieret.", "ok");
    } catch (fejl) {
        // uden adgang til udklipsholderen må linket markeres og kopieres i hånden
        skriv("Kunne ikke kopiere. Markér linket og tryk Ctrl/Cmd + C.", "fejl");
    }
}

document.addEventListener("submit", (hændelse) => {
    const besked = hændelse.target.dataset.bekræft;
    if (besked && !window.confirm(besked)) {
        hændelse.preventDefault();
    }
});

// hent titel, pris og billede fra produktlinket

const knap = document.getElementById("hent-fra-link");

if (knap) {
    const linkfelt = document.getElementById("link");
    const status = document.getElementById("skrab-status");
    const csrf = document.querySelector("input[name='_csrf']").value;

    const sæt = (felt, værdi) => {
        if (værdi && felt && !felt.value) felt.value = værdi;
    };

    const skriv = (tekst, klasse) => {
        status.textContent = tekst;
        status.className = "status " + (klasse || "");
    };

    knap.addEventListener("click", async () => {
        const url = linkfelt.value.trim();
        if (!url) {
            skriv("Indsæt et link først.", "fejl");
            return;
        }

        knap.disabled = true;
        skriv("Henter oplysninger …", "arbejder");

        try {
            const svar = await fetch("/api/skrab", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
                body: JSON.stringify({ url }),
            });
            const data = await svar.json();

            if (!svar.ok) {
                skriv(data.fejl || "Kunne ikke hente oplysninger.", "fejl");
                return;
            }

            sæt(document.getElementById("titel"), data.titel);
            if (data.pris !== null && data.pris !== undefined) {
                sæt(document.getElementById("pris"), String(data.pris).replace(".", ","));
            }

            const billedfelt = document.getElementById("billede_url");
            sæt(billedfelt, data.billede);

            const forhåndsvisning = document.getElementById("billede-forhåndsvisning");
            if (data.billede && forhåndsvisning && !forhåndsvisning.getAttribute("src")) {
                forhåndsvisning.src = data.billede;
                forhåndsvisning.classList.remove("skjult");
            }

            const fundet = [];
            if (data.titel) fundet.push("titel");
            if (data.pris !== null && data.pris !== undefined) fundet.push("pris");
            if (data.billede) fundet.push("billede");

            if (!fundet.length) {
                skriv("Fandt ingen oplysninger på siden. Udfyld felterne selv.", "fejl");
            } else if (data.valuta && data.valuta !== "DKK") {
                skriv(`Fandt ${fundet.join(", ")} – men prisen står i ${data.valuta}, så ret den til kroner.`, "fejl");
            } else {
                skriv(`Hentede ${fundet.join(", ")}. Tomme felter er udfyldt – ret dem gerne til.`, "ok");
            }
        } catch (fejl) {
            skriv("Kunne ikke kontakte serveren.", "fejl");
        } finally {
            knap.disabled = false;
        }
    });
}

// søg i oversigten over de andre på siden: rækkerne er der i forvejen, så
// filtreringen kan ske her og nu uden at hente noget

document.addEventListener("input", (hændelse) => {
    const felt = hændelse.target.closest("[data-søg]");
    if (!felt) return;

    const liste = document.getElementById(felt.dataset.søg);
    if (!liste) return;

    const søgt = felt.value.trim().toLowerCase();
    let fundet = 0;

    for (const række of liste.children) {
        const passer = !søgt || (række.dataset.navn || "").includes(søgt);
        række.classList.toggle("skjult", !passer);
        if (passer) fundet++;
    }

    const tom = document.getElementById(felt.dataset.søg + "-tom");
    if (tom) tom.classList.toggle("skjult", fundet > 0);
});
