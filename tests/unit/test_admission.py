"""Jeton d'admission de la file d'attente (BIL-015, `commun.admission`).

Review BIL-015, « À couvrir dans la passe de tests finale », point 1 : aller-retour, altération
d'un octet, autre séance, autre `sub`, expiration (limite comprise), jetons mal formés, clé trop
courte à la signature comme à la vérification.
"""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from commun.admission import (
    LONGUEUR_MIN_CLE,
    AdmissionInvalide,
    signer_admission,
    verifier_admission,
)

MAINTENANT = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
ECHEANCE = MAINTENANT + timedelta(minutes=10)
SUB = "sujet-client-test"


def _cle() -> str:
    return secrets.token_urlsafe(48)


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def _jeton_signe(charge_brute: bytes, cle: str) -> str:
    """Jeton correctement signé autour d'une charge arbitraire (mal formée exprès)."""
    charge = _b64(charge_brute)
    signature = _b64(hmac.new(cle.encode(), charge.encode(), hashlib.sha256).digest())
    return f"{charge}.{signature}"


def _alterer(texte: str, indice: int) -> str:
    remplacant = "A" if texte[indice] != "A" else "B"
    return texte[:indice] + remplacant + texte[indice + 1 :]


def test_un_jeton_signe_est_accepte_et_rend_son_echeance() -> None:
    cle = _cle()
    seance_id = uuid4()
    jeton = signer_admission(seance_id, SUB, ECHEANCE, cle)

    echeance = verifier_admission(
        jeton, seance_id=seance_id, sub=SUB, maintenant=MAINTENANT, cle=cle
    )

    assert echeance == ECHEANCE


def test_la_meme_admission_donne_toujours_le_meme_jeton() -> None:
    cle = _cle()
    seance_id = uuid4()

    assert signer_admission(seance_id, SUB, ECHEANCE, cle) == signer_admission(
        seance_id, SUB, ECHEANCE, cle
    )


@pytest.mark.parametrize("partie", ["charge", "signature"])
def test_un_jeton_altere_d_un_caractere_est_refuse(partie: str) -> None:
    cle = _cle()
    seance_id = uuid4()
    charge, signature = signer_admission(seance_id, SUB, ECHEANCE, cle).split(".")
    if partie == "charge":
        jeton = f"{_alterer(charge, 0)}.{signature}"
    else:
        jeton = f"{charge}.{_alterer(signature, 0)}"

    with pytest.raises(AdmissionInvalide):
        verifier_admission(jeton, seance_id=seance_id, sub=SUB, maintenant=MAINTENANT, cle=cle)


def test_un_jeton_signe_par_une_autre_cle_est_refuse() -> None:
    seance_id = uuid4()
    jeton = signer_admission(seance_id, SUB, ECHEANCE, _cle())

    with pytest.raises(AdmissionInvalide):
        verifier_admission(jeton, seance_id=seance_id, sub=SUB, maintenant=MAINTENANT, cle=_cle())


def test_un_jeton_d_une_autre_seance_est_refuse() -> None:
    cle = _cle()
    jeton = signer_admission(uuid4(), SUB, ECHEANCE, cle)

    with pytest.raises(AdmissionInvalide):
        verifier_admission(jeton, seance_id=uuid4(), sub=SUB, maintenant=MAINTENANT, cle=cle)


def test_un_jeton_d_un_autre_appelant_est_refuse() -> None:
    cle = _cle()
    seance_id = uuid4()
    jeton = signer_admission(seance_id, SUB, ECHEANCE, cle)

    with pytest.raises(AdmissionInvalide):
        verifier_admission(
            jeton, seance_id=seance_id, sub="autre-sujet-test", maintenant=MAINTENANT, cle=cle
        )


@pytest.mark.parametrize("decalage", [timedelta(0), timedelta(seconds=1), timedelta(hours=1)])
def test_un_jeton_expire_ou_a_son_echeance_exacte_est_refuse(decalage: timedelta) -> None:
    cle = _cle()
    seance_id = uuid4()
    jeton = signer_admission(seance_id, SUB, ECHEANCE, cle)

    with pytest.raises(AdmissionInvalide):
        verifier_admission(
            jeton, seance_id=seance_id, sub=SUB, maintenant=ECHEANCE + decalage, cle=cle
        )


def test_un_jeton_une_seconde_avant_son_echeance_est_accepte() -> None:
    cle = _cle()
    seance_id = uuid4()
    jeton = signer_admission(seance_id, SUB, ECHEANCE, cle)

    echeance = verifier_admission(
        jeton,
        seance_id=seance_id,
        sub=SUB,
        maintenant=ECHEANCE - timedelta(seconds=1),
        cle=cle,
    )

    assert echeance == ECHEANCE


@pytest.mark.parametrize(
    "cas",
    [
        "vide",
        "sans_point",
        "charge_vide",
        "signature_vide",
        "base64_invalide",
        "utf8_invalide",
        "deux_champs",
        "quatre_champs",
        "expiration_non_entiere",
        "seance_non_uuid",
    ],
)
def test_un_jeton_mal_forme_est_refuse(cas: str) -> None:
    cle = _cle()
    seance_id = uuid4()
    expiration = str(int(ECHEANCE.timestamp()))
    valide_charge, valide_signature = signer_admission(seance_id, SUB, ECHEANCE, cle).split(".")
    jetons = {
        "vide": "",
        "sans_point": valide_charge + valide_signature,
        "charge_vide": f".{valide_signature}",
        "signature_vide": f"{valide_charge}.",
        # Signature valide d'une charge qui n'est pas du base64url (1 caractère : illisible).
        "base64_invalide": _signe_texte("A", cle),
        "utf8_invalide": _jeton_signe(b"\xff\xfe\xfd", cle),
        "deux_champs": _jeton_signe(f"{seance_id}|{SUB}".encode(), cle),
        "quatre_champs": _jeton_signe(f"{seance_id}|{SUB}|x|{expiration}".encode(), cle),
        "expiration_non_entiere": _jeton_signe(f"{seance_id}|{SUB}|demain".encode(), cle),
        "seance_non_uuid": _jeton_signe(f"pas-un-uuid|{SUB}|{expiration}".encode(), cle),
    }

    with pytest.raises(AdmissionInvalide):
        verifier_admission(
            jetons[cas], seance_id=seance_id, sub=SUB, maintenant=MAINTENANT, cle=cle
        )


def _signe_texte(charge: str, cle: str) -> str:
    """Jeton signé dont la charge est un texte brut (pas forcément du base64url)."""
    signature = _b64(hmac.new(cle.encode(), charge.encode(), hashlib.sha256).digest())
    return f"{charge}.{signature}"


@pytest.mark.parametrize("cle", ["", "c" * (LONGUEUR_MIN_CLE - 1)])
def test_une_cle_trop_courte_est_refusee_a_la_signature(cle: str) -> None:
    with pytest.raises(RuntimeError):
        signer_admission(uuid4(), SUB, ECHEANCE, cle)


@pytest.mark.parametrize("cle", ["", "c" * (LONGUEUR_MIN_CLE - 1)])
def test_une_cle_trop_courte_est_refusee_a_la_verification(cle: str) -> None:
    seance_id = uuid4()
    jeton = signer_admission(seance_id, SUB, ECHEANCE, _cle())

    with pytest.raises(RuntimeError):
        verifier_admission(jeton, seance_id=seance_id, sub=SUB, maintenant=MAINTENANT, cle=cle)


def test_une_cle_de_trente_deux_caracteres_suffit() -> None:
    cle = "c" * LONGUEUR_MIN_CLE
    seance_id = uuid4()
    jeton = signer_admission(seance_id, SUB, ECHEANCE, cle)

    assert (
        verifier_admission(jeton, seance_id=seance_id, sub=SUB, maintenant=MAINTENANT, cle=cle)
        == ECHEANCE
    )


def test_la_signature_est_comparee_a_temps_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    """La signature et le `sub` passent par `hmac.compare_digest`, jamais par `==`."""
    cle = _cle()
    seance_id = uuid4()
    jeton = signer_admission(seance_id, SUB, ECHEANCE, cle)
    comparaisons: list[tuple[bytes, bytes]] = []
    original = hmac.compare_digest

    def espion(a: bytes, b: bytes) -> bool:
        comparaisons.append((a, b))
        return original(a, b)

    monkeypatch.setattr(hmac, "compare_digest", espion)

    verifier_admission(jeton, seance_id=seance_id, sub=SUB, maintenant=MAINTENANT, cle=cle)

    signature = jeton.split(".")[1].encode()
    assert (signature, signature) in comparaisons
    assert (SUB.encode(), SUB.encode()) in comparaisons
