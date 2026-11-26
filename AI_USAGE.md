# AI usage

Keep all three headings exactly as they are. If this file is missing or any heading is
missing, the grader stops and gives 0 ("AI_USAGE.md missing or incomplete"). The content
is not scored, but your Track Mentor reads it and the W8 defence can ask about it.

## Tools

Used AI assistant (Antigravity) to explain the task requirements, review `app/budget.py`, and implement `app/stream.py` and `app/main.py`.

## What AI got wrong

Initially, `app/main.py` returned `EventSourceResponse(event_generator())` directly from the route handler, which caused `test_http_endpoint_speaks_server_sent_events` to fail with `AttributeError: 'ServerSentEvent' object has no attribute 'encode'`. Switching the route to `@app.post("/v1/clauses/explain", response_class=EventSourceResponse)` with a `Depends(prepare)` dependency and an exception handler for 429 fixed the SSE serialization.

## In my own words

<!-- Answer without AI, one or two sentences each. -->

1. Why is it safe to switch provider before the first token and not after?
before the first token the switch will not effect because there is no output has been generated yet so it will be like we clean restart and the user will not notice any change but if we switch after the first token it will effect the response and will break it or may create a incomplete response and the user experience will be very bad

2. Which checks did you put before the stream starts, and why could they not be error events instead?
before the stream start we check on the inputs (x-tentant-id, cluase_text, language if ar or en only) and return 422 if any of the inputs are invalid and also we check the budget if the minimum cost is more than the tenant's budget will return 429 error and all of these checks can't be error events because when the stream starts it return status code 200 and we can send more than one status code in the http protocol and if we make it is error events this will not be handled by the http error handler and will be waste of resources to open the stream the check then close it 