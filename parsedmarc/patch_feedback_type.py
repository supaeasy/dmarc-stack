"""Workaround für nicht-standardkonforme DMARC-Forensic-Reports.

Manche Mail-Gateways (z.B. Exim/cPanel-basierte wie secure-mailgate.com bei
dogado) verschicken Forensic-Reports ohne den maschinenlesbaren
message/feedback-report-Teil — nur mit der Klartext-Zusammenfassung
("A message claiming to be from you has failed ...").

parsedmarc hat für genau dieses Format einen Text-Fallback, der aber nur
Arrival-Date und Source-IP liefert. Der Elasticsearch-Sink (elastic.py)
verlangt zusätzlich kompromisslos feedback_type und authentication_results
und verwirft den Report sonst mit
  "Failure report missing required field: 'feedback_type'".

Dieses Skript wrappt parse_failure_report und füllt die beiden Felder mit
Defaults, damit solche Reports trotzdem in Elasticsearch landen. Es wird in
docker-compose.yml als Entrypoint vor die normale CLI geschaltet:

    entrypoint: ["python", "/patch_feedback_type.py"]
    command:    ["-c", "/parsedmarc.ini"]

Geprüft gegen parsedmarc 10.2.2. Sollte ein künftiges parsedmarc-Release
das Problem upstream beheben, ist dieser Patch wirkungslos-harmlos
(setdefault greift dann nie) und kann entfernt werden.
"""

import parsedmarc

_orig_parse_failure_report = parsedmarc.parse_failure_report


def _parse_failure_report_with_defaults(*args, **kwargs):
    report = _orig_parse_failure_report(*args, **kwargs)
    # Nur setzen, wenn der Report die Felder nicht selbst mitbringt.
    report.setdefault("feedback_type", "auth-failure")
    report.setdefault("authentication_results", "")
    return report


parsedmarc.parse_failure_report = _parse_failure_report_with_defaults

from parsedmarc.cli import _main  # noqa: E402

if __name__ == "__main__":
    _main()
