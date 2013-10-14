DROP TABLE metadata;
CREATE TABLE metadata (
       key VARCHAR(255),
       value TEXT
);

DROP TABLE feed_items;
CREATE TABLE feed_items (
       id SERIAL PRIMARY KEY,
       title TEXT,
       link TEXT,
       text TEXT,
       created TIMESTAMP,
       published TIMESTAMP
);

DROP TABLE categories;
CREATE TABLE categories (
       id SERIAL PRIMARY KEY,
       next_id INT,
       prev_id INT,
       name VARCHAR(255),
       slug VARCHAR(255),
       description TEXT
);

DROP TABLE sections;
CREATE TABLE sections (
       id SERIAL PRIMARY KEY,
       next_id INT,
       prev_id INT,
       name VARCHAR(255),
       slug VARCHAR(255),
       description TEXT,
       category INT
);

DROP TABLE data_items;
CREATE TABLE data_items (
       id SERIAL PRIMARY KEY,
       next_id INT,
       prev_id INT,
       title TEXT,
       link TEXT,
       text TEXT,
       meta TEXT,
       section INT
);