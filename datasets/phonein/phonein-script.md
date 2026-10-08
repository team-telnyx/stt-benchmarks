# Phone-in reading script, Scribe benchmark (v1, 2026-10-01)
Ground-truth script for the Telnyx phone-in recording line. Callers read it over real PSTN, giving 8 kHz phone audio with a known transcript.
Three packs, 75 numbered lines: NAMES and ALPHANUMERICS (N01-N25), SHORT TURNS (S01-S30), MEDICAL PHONE (M01-M20).
Line ids are spoken aloud ("N one", "S twelve") so the recording can be segmented by finding the spoken ids.
Full read takes about 8 to 9 minutes at a natural pace. The line holds up to 15 minutes.
All names, addresses, numbers, IDs, and emails below are invented. Do not substitute your own personal details.
The text after the line id is the exact ground truth. Scoring ignores the spoken line id itself.

## How to read

1. Call the number in `phonein-status.md` from any phone. A mobile in a normal room is ideal. Speakerphone is fine too.
2. Wait for the beep after the greeting.
3. For each line, say the line id first ("N one"), pause briefly, then read the line.
4. Pause about 2 seconds between lines. In the SHORT TURNS pack, pause a full 2 seconds after every word.
5. Read at your normal pace and in your normal accent. Every accent helps. Do not over-enunciate.
6. If you stumble, say "again" and re-read the whole line, id included.
7. Spell letters as single letters ("T, A, U"). Read digits one at a time unless the line says otherwise.
8. Press # or hang up when you finish.

Before the first line, please say your first name, your native language, and what phone you are using (example: "Priya, Hindi, iPhone on speaker").

## Pack N: names and alphanumerics

- N01. My name is Taulant Berisha.
- N02. That's Taulant, T A U L A N T.
- N03. The patient's name is Siobhan Nguyen-Okafor.
- N04. Last name Okafor, O K A F O R.
- N05. I'm calling for Xiomara Szczepanski.
- N06. Szczepanski is S Z C Z E P A N S K I.
- N07. This is Oluwaseun Adeyemi, and my wife is Saoirse.
- N08. Please ask for Dr. Bartholomew Achterberg.
- N09. You can reach Thandiwe Mbeki-Lindqvist at extension 4417.
- N10. My address is 4821 Wisteria Lane, Apartment 3B, Tucson, Arizona 85719.
- N11. Ship it to 17 Quail Run Court, Schenectady, New York 12309.
- N12. The house number is 10350, on North Kedzie Avenue in Chicago.
- N13. My callback number is 415 555 0187.
- N14. You can also try 310 555 0142, extension 22.
- N15. My date of birth is March 9th, 1987.
- N16. Born on 11/04/1962.
- N17. My member ID is W X 4 7 2 9 1 8 3 K.
- N18. The policy number is H M O dash 8 8 3 0 2 7 Z.
- N19. Group number 0 0 4 5 1 B, as in boy.
- N20. My confirmation code is Q 7 F as in Frank, 9 9 L.
- N21. The claim number is 2026 dash 0 4 1 7 dash 3 3 8.
- N22. My email is taulant.berisha@gmail.com.
- N23. That's j dot okafor 82 at outlook dot com.
- N24. Send it to xiomara_s@protonmail.com.
- N25. My zip code is 9 4 1 0 7, and my PIN is 6 0 3 9.

## Pack S: short turns

Say each one alone, then pause a full 2 seconds.

- S01. Yes.
- S02. No.
- S03. Yeah.
- S04. Nope.
- S05. Correct.
- S06. That's right.
- S07. Mm-hmm.
- S08. Uh-huh.
- S09. Okay.
- S10. Sure.
- S11. Yep.
- S12. No thanks.
- S13. Not really.
- S14. Exactly.
- S15. Hello?
- S16. Two.
- S17. Seven.
- S18. Fifteen.
- S19. Zero.
- S20. Forty.
- S21. B.
- S22. M.
- S23. F.
- S24. S.
- S25. Z.
- S26. Yes, please.
- S27. Hold on.
- S28. Sorry?
- S29. Uh, no.
- S30. Bye.

## Pack M: medical phone calls

Read these like a patient calling a clinic or pharmacy.

- M01. Hi, I need a refill on my lisinopril, 10 milligrams, once a day.
- M02. I'm out of metformin 500 milligrams, I take it twice daily with meals.
- M03. Can you send my atorvastatin 40 milligrams to the Walgreens on Mission Street?
- M04. My doctor started me on Eliquis 5 milligrams, and I've been getting nosebleeds.
- M05. I take levothyroxine 75 micrograms every morning.
- M06. I'm calling about my son's amoxicillin, 250 milligrams per 5 milliliters.
- M07. I've had a fever of 101.5 and a dry cough for three days.
- M08. I've been having chest tightness and shortness of breath when I climb stairs.
- M09. The pain is in my lower right abdomen, about a 7 out of 10.
- M10. I'm allergic to penicillin and sulfa drugs.
- M11. My pharmacy is the CVS on 3rd Avenue, their number is 212 555 0163.
- M12. I switched to Rite Aid on El Camino Real.
- M13. My insurance is Blue Cross Blue Shield, PPO plan.
- M14. I have Aetna, but my secondary is Medicare Part B.
- M15. We're on UnitedHealthcare through my husband's employer.
- M16. My Kaiser Permanente medical record number is 1 1 0 4 7 7 2 6.
- M17. I need a prior authorization for Ozempic, 0.5 milligrams weekly.
- M18. I take sertraline 50 milligrams and gabapentin 300 milligrams at night.
- M19. Can I take ibuprofen with my warfarin?
- M20. I'd like to reschedule my appointment with Dr. Ramanathan to next Tuesday at 2:30.

## Notes for scoring

- Ground truth is the line text exactly as written above, minus the "N01." style prefix.
- Phone numbers use the reserved fictional 555-01XX range. Member and policy IDs are invented.
- S-pack scoring: exact-match after normalization, plus wrong-language detection (a "Yes" transcribed as "Ja" or "Oui" is a failure).
- M-pack term list (drug, dose, unit, carrier, pharmacy) is fixed from this script before any engine runs.
