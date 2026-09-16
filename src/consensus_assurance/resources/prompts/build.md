Generate the selected implementation-grounded local model using the loaded method.
Return one BuildReply: a complete Bundle when justified, or a ModelDraft with the
available Behavior/Properties/configuration and typed pending_work. A missing
harness or observation assembly must not discard an already justified model.
Requests attached to pending_work will resume the saved components. If core
behavior/property evidence is missing, say so under that component: the controller
will save the draft but must not execute it as the original audit question.
Alternatively return neither artifact, a precise gap and focused requests.
Preserve selected goal/obligation meaning. Do not invent guards or environment
truths to make a draft executable. Model-only search remains uncalibrated.
