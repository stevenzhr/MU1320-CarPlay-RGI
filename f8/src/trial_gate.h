#ifndef MU1320_TRIAL_GATE_H
#define MU1320_TRIAL_GATE_H

/* F7 daily gate.  Same entry points as the one-shot navhook gate, so the
 * hook_framework.c patch that calls them is unchanged.
 * Called only from real interposed runtime boundaries, never constructors. */
int trial_gate_active(void);
/* Destructor-safe query: does not decide an undecided gate. */
int trial_gate_was_active(void);
/* Live-DIO guard: 1 while this process is the newest active DIO generation
 * (or the generation record is unreadable).  The bus connector of a
 * superseded generation stops (re)connecting to Java. */
int trial_gate_is_current(void);

#endif
