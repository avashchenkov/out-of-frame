# Vision

## The problem

A flat listing shows what the seller or landlord wants you to see. Problems that cost a buyer
or a tenant later are often outside the photo: a wastewater treatment plant behind a new
building, an industrial site that is never in the news, a motorway that is planned but not
built yet. Nobody who sells or rents out the flat has to tell you about them, and the person
moving in rarely knows what to check or where to look.

## The solution

Out of Frame is an AI agent that checks the area around a flat for such problems. The user
pastes a listing or an address. The agent asks where they travel regularly and at what times.
Then it returns a report: what is nearby, what it is, why it matters to someone living there,
and the source of each fact. Objects it could not identify are listed too.

It checks five kinds of object, each within its own radius:

- **industrial and energy sites**: pollution, noise, risk of accidents;
- **wastewater treatment plants**: smell;
- **airports**: aircraft noise;
- **major roads and railways**, including planned ones: noise;
- **planned development**: what will be built nearby.

For each place the user travels to regularly, it adds the public transport trip there and
back at the user's usual times.

## Out of scope

It reports facts and gives no advice: it does not say whether to take the flat, gives no
overall score and does not look at prices or rents. It covers Berlin only. It is not a
product or a public service.

## Why an agent

Official registers list what is already built and registered. A chat model has no map and no
checklist. The most important facts are often in neither. One example is an industrial site
that is never in the news: a search for the address finds nothing, but the map shows an
unnamed industrial area next door. Another is a planned project whose status is only in a PDF
on a city website. To find such facts, the agent investigates each object separately: it
searches, reads the results and decides whether the object is now clear. That is the agent's
work; collecting the data is ordinary code.

The agent knows what to check when choosing a home, but it does not know the city. The
checklist is built in. What is actually near the address comes from current maps, plans and
web pages, never from the model's memory.
