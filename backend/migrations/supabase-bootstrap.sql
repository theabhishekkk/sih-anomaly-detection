-- Run once in the Supabase SQL Editor after replacing the password placeholder.
-- Store the same password in Render's DATABASE_URL and GitHub's DATABASE_URL
-- Actions secret. Use a long, unique random password.
create role burnin_app
  with login
  password 'REPLACE_WITH_A_LONG_RANDOM_PASSWORD'
  nosuperuser
  nocreatedb
  nocreaterole
  noreplication;

grant connect on database postgres to burnin_app;
grant usage, create on schema public to burnin_app;
