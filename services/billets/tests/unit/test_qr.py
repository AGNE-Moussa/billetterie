"""Contenu signé du QR code d'un billet (CA2 du plan BIL-009, H3, décision Q6), sans base.

`signer`, `contenu_qr` et `verifier_qr` sont appelés directement, avec une clé générée.
"""

import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from billets.domaine.emission import billets_a_emettre
from billets.domaine.qr import QrInvalide, contenu_qr, signer, verifier_qr

MAINTENANT = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
# HMAC-SHA256 (32 octets) en base64url sans remplissage : 43 caractères.
FORMAT_QR = re.compile(
    r"(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"\.(?P<sig>[A-Za-z0-9_-]{43})"
)


@pytest.fixture
def cle() -> str:
    return secrets.token_urlsafe(32)


def test_verifier_qr_rend_l_identifiant_du_billet(cle: str) -> None:
    billet_id = uuid4()

    assert verifier_qr(contenu_qr(billet_id, cle), cle) == billet_id


def test_le_qr_porte_l_identifiant_et_sa_signature_sans_donnee_lisible(cle: str) -> None:
    a1, a2 = uuid4(), uuid4()
    data = {
        "commande_id": str(uuid4()),
        "client": "client-test",
        "email": "client.test@exemple.test",
        "seance_id": str(uuid4()),
        "lignes": [{"place_id": str(a1), "montant": 4500}, {"place_id": str(a2), "montant": 4500}],
        "montant_total": 9000,
    }

    billets = billets_a_emettre(data, emis_le=MAINTENANT, cle=cle)

    assert billets
    for billet in billets:
        contenu = billet.qr_code
        trouve = FORMAT_QR.fullmatch(contenu)
        assert trouve, contenu
        assert trouve.group("id") == str(billet.id)
        assert contenu == f"{billet.id}.{signer(billet.id, cle)}"
        assert "=" not in contenu
        for lisible in ("client-test", "client.test", "exemple.test", "4500", "9000"):
            assert lisible not in contenu, lisible
        # Ni la place, ni la séance, ni la commande.
        for identifiant in (str(billet.place_id), str(billet.seance_id), str(billet.commande_id)):
            assert identifiant not in contenu, identifiant


def _changer_un_caractere(texte: str, position: int, alphabet: str) -> str:
    actuel = texte[position]
    remplacant = next(c for c in alphabet if c != actuel)
    return texte[:position] + remplacant + texte[position + 1 :]


Alteration = Callable[[UUID, str], str]

ALTERATIONS: dict[str, Alteration] = {
    # Premier caractère de l'identifiant : un autre UUID valide, sans sa signature.
    "identifiant_change": lambda b, cle: _changer_un_caractere(
        contenu_qr(b, cle), 0, "0123456789abcdef"
    ),
    # Premier caractère de la signature (le dernier ne porte que des bits de remplissage).
    "signature_changee": lambda b, cle: _changer_un_caractere(
        contenu_qr(b, cle), len(str(b)) + 1, "ABCDEFGH"
    ),
    "signature_d_un_autre_billet": lambda b, cle: f"{b}.{signer(uuid4(), cle)}",
    "tronque": lambda b, cle: contenu_qr(b, cle)[:-5],
    "sans_separateur": lambda b, cle: contenu_qr(b, cle).replace(".", ""),
    "vide": lambda b, cle: "",
    "identifiant_non_uuid": lambda b, cle: f"pas-un-uuid.{signer(b, cle)}",
}


@pytest.mark.parametrize("alteration", list(ALTERATIONS.values()), ids=list(ALTERATIONS))
def test_un_qr_modifie_est_refuse(cle: str, alteration: Alteration) -> None:
    billet_id = uuid4()
    contenu = alteration(billet_id, cle)
    rendu: Any = None

    with pytest.raises(QrInvalide):
        rendu = verifier_qr(contenu, cle)

    assert rendu is None


def test_un_qr_signe_avec_une_autre_cle_est_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    cle_1, cle_2 = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    billet_id = uuid4()
    contenu = contenu_qr(billet_id, cle_1)

    with pytest.raises(QrInvalide):
        verifier_qr(contenu, cle_2)
    # Clé lue dans l'environnement (cle=None) : QR_CLE_SIGNATURE = clé 2.
    monkeypatch.setenv("QR_CLE_SIGNATURE", cle_2)
    with pytest.raises(QrInvalide):
        verifier_qr(contenu)
