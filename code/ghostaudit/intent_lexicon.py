"""Principled, language-aware lexicon for deletion intent (SPEC 9.2).

Fallback for `--llm off`, cache misses and low-confidence model answers, and the
disagreement detector against the LLM (SPEC 9.4). The rules are general
linguistic patterns for EN, FR, ES, PT, JA and KO, not sentences copied from
dataset requests. The default is DELETION, because a request can ask for
deletion without naming a verb ("confirm that the profile is gone").

A text is NON_DELETION only when it has no unnegated deletion verb and at least
one of these signals holds:

* (a) negated verb: a deletion verb or noun (`delete`, `deletion`,
  `suppression`, `supresion`, `cierre`, `remocao`, ...) preceded, in the same
  clause and within `INTENT_NEGATION_WINDOW` tokens, by a negator of its
  language (`not`, `ne ... pas`, `no`, `nao`, `sem`) with no clause connector
  between them, or directly followed by a negative object (`delete nothing`,
  `ne supprimez rien`). JA and KO negate with a verb suffix (`削除しないで`,
  `삭제하지 마`); in KO the negated predicate may also follow the verb noun
  after a particle and a space (`탈퇴를 원하지 않습니다`).
* (b) keep-active: keep/leave/continue ... account/profile ... active/open/as is.
* (c) primary intent is access, correction, export, copy, invoice, login help
  or opt-out.

Deviation from the literal wording of SPEC 9.2 ("NON_DELETION if any holds"):
an unnegated deletion verb wins, so "delete my account but do not delete my
invoices" stays a deletion. A retention permission is a clause that names a
retained record class (backups, logs, statistics, invoices, ...) and a
permission cue (may, can, if required, ...), such as "you can keep anonymous
statistics", "retain backups if required" or "security records can stay".
As SPEC 9.2 requires, such a clause never counts for (a) or (b); its
unnegated deletion verbs still count ("delete my account and any logs you
may have" is a deletion) and it is still read for (c).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import FrozenSet, List, Pattern, Tuple

from ghostaudit.config import INTENT_NEGATION_WINDOW

SIGNAL_UNNEGATED = "unnegated_deletion_verb"
SIGNAL_NEGATED = "negated_deletion_verb"
SIGNAL_KEEP_ACTIVE = "keep_account_active"
SIGNAL_OTHER_INTENT = "access_or_correction_intent"
SIGNAL_DEFAULT = "no_non_deletion_signal"

_CLAUSE_BREAK = re.compile(r"[.,;:!?()\n。、]")
_COMBINING_MARKS = re.compile("[̀-ͯ]")
_TOKEN = re.compile(r"[a-z]+")


def _patterns(*sources: str) -> Pattern[str]:
    return re.compile("|".join(sources))


@dataclass(frozen=True)
class _Language:
    """Deletion verb and noun stems, negators, negative objects and clause connectors."""

    verbs: Pattern[str]
    negators: FrozenSet[str]
    negative_objects: FrozenSet[str]
    connectors: FrozenSet[str]


_LATIN_LANGUAGES: Tuple[_Language, ...] = (
    _Language(
        re.compile(
            r"^(?:delet\w*|eras\w*|remov\w*|clos(?:e|es|ed|ing|ure)|cancel\w*"
            r"|wip(?:e|es|ed|ing)|purg\w*|destroy\w*)$"
        ),
        frozenset({"not", "never", "without", "nor", "neither"}),
        frozenset({"nothing", "none"}),
        frozenset({
            "and", "but", "so", "because", "then", "please", "however", "since", "while",
            "although", "yet", "if", "as", "therefore", "hence", "how", "sure", "able",
            "certain", "know", "whether", "where", "why", "what",
        }),
    ),
    _Language(
        re.compile(
            r"^(?:supprim\w*|suppression\w*|effac\w*|ferm(?:e|er|ez|ent|eture)|clotur\w*"
            r"|resili\w*|annul\w*)$"
        ),
        frozenset({"pas", "jamais", "sans", "nullement"}),
        frozenset({"rien", "aucun", "aucune"}),
        frozenset({"et", "mais", "donc", "car", "parce", "puis", "veuillez", "si", "alors", "comment"}),
    ),
    _Language(
        re.compile(
            r"^(?:elimin\w*|borr\w*|cerr(?:ar|e|en|ada|ado)|cierr\w*|cancel\w*|suprim\w*|supres\w*)$"
        ),
        frozenset({"no", "nunca", "jamas", "sin", "ni", "tampoco"}),
        frozenset({"nada", "ninguno", "ninguna", "ningun"}),
        frozenset({"y", "e", "pero", "porque", "asi", "entonces", "favor", "si", "como", "donde"}),
    ),
    _Language(
        re.compile(r"^(?:exclu\w*|apag\w*|elimin\w*|remov\w*|remoc\w*|cancel\w*|encerr\w*)$"),
        frozenset({"nao", "nunca", "jamais", "sem", "nem"}),
        frozenset({"nada", "nenhum", "nenhuma"}),
        frozenset({"e", "mas", "porque", "entao", "pois", "favor", "se", "como", "onde"}),
    ),
)

# Verb followed (within a few characters, same clause) by a negating suffix. Korean
# separates words with spaces, so its negated predicate may also follow the verb noun
# after an optional particle and a space ("탈퇴를 원하지 않", "삭제 하지 마").
_JA_VERB = re.compile(r"削除|消去|抹消|退会|解約|消[さしすせ]")
_JA_NEGATION = re.compile(
    r"[^\s]{0,6}?(?:しない|しません|せず|さない|しなくて|不要|いりません|いらない|やめて|ないで"
    r"|たくない|たくありません|ほしくない|欲しくない|望まない|望みません|希望しません)"
)
_KO_VERB = re.compile(r"삭제|탈퇴|제거|해지|지우|지워")
_KO_NEGATION = re.compile(
    r"(?:[^\s]{0,8}?|[을를은는이가도]?\s+)"
    r"(?:하지\s*(?:마|말|않|못)|지\s*(?:마|말|않)|원하지\s*않|원치\s*않|필요\s*없|말아|마세요|마십시오)"
)

# Contractions and idioms folded to the tokens the rules read (all after casefold).
_MODAL_CONTRACTION = re.compile(r"\b(?:can|won|shan)'t\b")
_NOT_CONTRACTION = re.compile(r"n't\b")
_IDIOMS: Tuple[Tuple[Pattern[str], str], ...] = (
    (re.compile(r"\bdo not hesitate\b"), "please"),
    (re.compile(r"\bwithout (?:any |further )?delay\b"), "promptly"),
    (re.compile(r"\b(?:no need to|instead of|refrain from|rather than)\b"), "not"),
    # French "ne <verb> pas|rien|aucun" brackets the verb; move the negator in front of it.
    (
        re.compile(r"\bn(?:e\s+|')((?:[a-z]+\s+){0,2}?[a-z]+)\s+(?:pas|jamais|point|rien|aucune?)\b"),
        r"pas \1",
    ),
)

# "remove me from the marketing list" opts out of messages; it does not delete the account.
_OPT_OUT_PHRASES = _patterns(
    r"\b(?:remove|delete|take)\w*\s+(?:me|my\s+\w+)\s+from\s+(?:the\s+|your\s+|all\s+|any\s+)?"
    r"(?:marketing|mailing|promotional|newsletter|email|subscriber)\b",
    r"\bcancel\w*\s+(?:a\s+)?(?:inscricao|assinatura)\b",
    r"\bdarme de baja de\s+(?:la\s+|las\s+|los\s+)?(?:lista|boletin|correos|promociones)\w*",
    r"\b(?:retir|supprim)\w+\s+(?:moi|mon (?:adresse|email))\s+de\s+(?:la\s+)?liste\b",
)
_OPT_OUT_TOKEN = "unsubscribe"

_RETAINED_OBJECT = re.compile(
    r"\b(?:backups?|archives?|logs?|audit\w*|security|securite|seguridad|seguranca|statistics?"
    r"|statistiques?|estadisticas?|estatisticas?|analytics|anonymi[sz]ed|anonym\w*|invoices?"
    r"|tax|legal|ledger|reference|tombstone|respaldos?|sauvegardes?|copia de seguridad)\b"
)
_PERMISSION_CUE = re.compile(
    r"\b(?:may|can|could|fine|ok|okay|allowed|permitted|required|necessary|needed|no need"
    r"|not need|not required|have to|peut|peuvent|pouvez|puede|pueden|pode|podem|requis)\b"
)

_KEEP_ACTIVE = _patterns(
    r"\b(?:keep|leave|maintain|continue|remain)\w*\b[^.;!?]{0,40}?\b(?:account|profile|membership"
    r"|subscription|service|it)\b[^.;!?]{0,30}?\b(?:active|open|as it is|as is|in place|intact"
    r"|untouched|unchanged|running)\b",
    r"\bcontinu\w*\b[^.;!?]{0,15}\b(?:us(?:e|ing)|have)\b[^.;!?]{0,25}\b(?:account|service|profile|it)\b",
    r"\bstill (?:use|need|want)\b[^.;!?]{0,20}\b(?:account|profile|service)\b",
    r"\b(?:garde[rz]?|conserve[rz]?|laisse[rz]?|maintene[rz])\b[^.;!?]{0,40}?\b(?:compte|profil)\b"
    r"[^.;!?]{0,30}?\b(?:actif|active|ouvert|ouverte|tel quel|intact)\b",
    r"\bcontinu\w*\s+a\s+utilis",
    r"\b(?:mantener|mantenga|dejar|deje|conservar|conserve)\b[^.;!?]{0,40}?\b(?:cuenta|perfil)\b"
    r"[^.;!?]{0,30}?\b(?:activa|abierta|tal cual|como esta|intacta)\b",
    r"\b(?:seguir|sigo|continuar|continuo)\s+(?:usando|utilizando)",
    r"\b(?:manter|mantenha|deixar|deixe)\b[^.;!?]{0,40}?\b(?:conta|perfil)\b"
    r"[^.;!?]{0,30}?\b(?:ativa|aberta|como esta|intacta)\b",
    r"\bcontinu\w*\s+(?:a\s+)?us(?:ar|o)\b",
    r"そのまま|引き続き[^。]{0,8}(?:利用|使)|(?:アカウント|プロフィール)[^。]{0,8}(?:維持|残して|残す)",
    r"(?:계정|프로필)[^.]{0,8}(?:유지|그대로)|계속\s*(?:사용|이용)",
)

_OTHER_INTENT = _patterns(
    r"\b(?:copy|copies)\b[^.;!?]{0,25}\b(?:data|information|details|account|invoices?|records?)\b",
    r"\bwhat\b[^.;!?]{0,25}\b(?:data|information)\b[^.;!?]{0,20}\b(?:hold|have|store|keep|collect)",
    r"\b(?:download|export)\w*\s+(?:of\s+)?(?:my|the|all|a|an)\b|\bportab\w+",
    r"\b(?:update|change|correct|fix|replace|rename)\s+(?:my|the|this|his|her)?\s*(?:\w+\s+)?"
    r"(?:name|surname|e-?mail|phone|number|address|details|spelling)\b",
    r"\b(?:misspell\w*|out of date)\b",
    r"\b(?:need|want|send|resend|get|obtain|request)\w*\b[^.;!?]{0,25}\b(?:invoices?|receipts?)\b",
    r"\b(?:unsubscribe|opt[- ]?out)\b|\bstop\b[^.;!?]{0,20}\b(?:emails?|promotional|marketing|newsletters?|messages?)",
    r"\b(?:reset|password|log ?in|locked out|cannot access|access my)\b",
    r"copie de mes donnees|quelles donnees|corriger|modifier mon|mettre a jour|telecharger mes|exporter mes"
    r"|(?:besoin|envoyez|copie)\b[^.;!?]{0,25}\bfactures?|desabonn|desinscri|mot de passe",
    r"copia de mis datos|que datos|corregir|actualizar|modificar mi|descargar mis|exportar mis"
    r"|(?:necesito|envie|copia)\b[^.;!?]{0,25}\bfacturas?|contrasena",
    r"copia dos meus dados|quais dados|corrigir|atualizar|alterar meu|baixar meus"
    r"|(?:preciso|quero|envie|copia)\b[^.;!?]{0,25}\b(?:faturas?|notas? fiscais)|\bsenha\b",
    r"コピー|写し|修正|訂正|変更|更新|ダウンロード|エクスポート|配信停止|メルマガ|請求書|領収書|パスワード|ログイン",
    r"사본|수정|변경|정정|내보내|다운로드|수신\s*거부|구독\s*취소|청구서|영수증|비밀번호|로그인",
)

# A keep verb that a negator precedes ("do not want to keep the account open") is no keep-active request.
_NEGATED_KEEP = re.compile(
    r"\b(?:not|never|pas|jamais|nunca|nao|nem)\b(?:\s+\w+){0,4}?\s+"
    r"(?:keep|maintain|leave|continue|remain|garder|conserver|laisser|mantener|dejar|conservar|manter|deixar)\w*"
)


@dataclass(frozen=True)
class _Clause:
    """One folded clause; `permission` marks a retention permission (SPEC 9.2)."""

    text: str
    permission: bool


@dataclass(frozen=True)
class LexiconVerdict:
    """Lexicon decision for one text; `signal` names the rule that decided it."""

    deletion: bool
    signal: str


def _fold(text: str) -> str:
    """Casefold, unify apostrophes and drop Latin diacritics (CJK marks are untouched)."""
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    stripped = _COMBINING_MARKS.sub("", unicodedata.normalize("NFD", text))
    return unicodedata.normalize("NFC", stripped)


def _expand_contractions(clause: str) -> str:
    return _NOT_CONTRACTION.sub(" not", _MODAL_CONTRACTION.sub("cannot", clause))


def _is_retention_permission(clause: str) -> bool:
    """A clause that permits keeping backups, statistics or similar records (SPEC 9.2)."""
    return bool(_RETAINED_OBJECT.search(clause) and _PERMISSION_CUE.search(clause))


def _normalize_clause(clause: str) -> str:
    for pattern, replacement in _IDIOMS:
        clause = pattern.sub(replacement, clause)
    return _OPT_OUT_PHRASES.sub(_OPT_OUT_TOKEN, clause)


def _clauses(text: str) -> List[_Clause]:
    """Folded clauses, each marked when it is a retention permission, ready for the rules."""
    folded = [_expand_contractions(c) for c in _CLAUSE_BREAK.split(_fold(text))]
    return [_Clause(_normalize_clause(c), _is_retention_permission(c)) for c in folded]


def _latin_verb_negated(tokens: List[str], index: int, language: _Language) -> bool:
    """True when a negator of `language` sits within the window before tokens[index],
    or a negative object of `language` directly follows it."""
    if index + 1 < len(tokens) and tokens[index + 1] in language.negative_objects:
        return True
    for back in range(1, INTENT_NEGATION_WINDOW + 1):
        if index - back < 0:
            return False
        token = tokens[index - back]
        if token in language.connectors:
            return False
        if token in language.negators:
            return True
    return False


def _count_latin(clause: str) -> Tuple[int, int]:
    """(negated, unnegated) deletion verbs among the Latin-script tokens of a clause."""
    tokens = _TOKEN.findall(clause)
    negated = unnegated = 0
    for index, token in enumerate(tokens):
        matching = [lang for lang in _LATIN_LANGUAGES if lang.verbs.match(token)]
        if not matching:
            continue
        if any(_latin_verb_negated(tokens, index, lang) for lang in matching):
            negated += 1
        else:
            unnegated += 1
    return negated, unnegated


def _count_suffix_negated(clause: str, verb: Pattern[str], negation: Pattern[str]) -> Tuple[int, int]:
    """(negated, unnegated) verbs for languages that negate with a verb suffix (JA, KO)."""
    negated = unnegated = 0
    for match in verb.finditer(clause):
        if negation.match(clause, match.end()):
            negated += 1
        else:
            unnegated += 1
    return negated, unnegated


def _count_verbs(clauses: List[_Clause]) -> Tuple[int, int]:
    """(negated, unnegated) deletion verbs; negations inside retention permissions do not count."""
    negated = unnegated = 0
    for clause in clauses:
        for found in (
            _count_latin(clause.text),
            _count_suffix_negated(clause.text, _JA_VERB, _JA_NEGATION),
            _count_suffix_negated(clause.text, _KO_VERB, _KO_NEGATION),
        ):
            if not clause.permission:
                negated += found[0]
            unnegated += found[1]
    return negated, unnegated


def _keeps_active(clause: _Clause) -> bool:
    """Rule (b): an unnegated keep-active construction outside a retention permission."""
    if clause.permission:
        return False
    return bool(_KEEP_ACTIVE.search(clause.text) and not _NEGATED_KEEP.search(clause.text))


def classify_text(text: str) -> LexiconVerdict:
    """Decide whether `text` authorizes deletion (SPEC 9.2)."""
    clauses = _clauses(text)
    negated, unnegated = _count_verbs(clauses)
    if unnegated:
        return LexiconVerdict(True, SIGNAL_UNNEGATED)
    if negated:
        return LexiconVerdict(False, SIGNAL_NEGATED)
    joined = ". ".join(c.text for c in clauses)
    if any(_keeps_active(c) for c in clauses):
        return LexiconVerdict(False, SIGNAL_KEEP_ACTIVE)
    if _OTHER_INTENT.search(joined):
        return LexiconVerdict(False, SIGNAL_OTHER_INTENT)
    return LexiconVerdict(True, SIGNAL_DEFAULT)
