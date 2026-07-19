# OpenDissertation Backend
Back-end source code for opendissertation.com

See [Evaluation](#evaluation) for explanations of how Codex accelerated our
workflow, where key decisions were made, and how GPT-5.6 and Codex were used.

## Quick start

### Prerequisites for Development

- [GitHub Account](https://github.com/)
- [Docker Hub Account](https://hub.docker.com/)
- [Docker Engine](https://docs.docker.com/get-started/get-docker/) or
  [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [OpenAI Account](https://openai.com)

### Installation

First, clone the repo and change directory into it with

```bash
$ git clone https://github.com/OpenDissertation/od_backend.git
$ cd od_backend
```

Copy [config.toml.example](config.toml.example) and rename the copy to
`config.toml`. Populate `OPENAI_API_KEY` with the value from your OpenAI account
for development. `config.toml` has been added to [.gitignore](.gitignore) and
[.dockerignore](.dockerignore) to avoid adding it to GitHub.

Open Docker or Docker Desktop and sign in. Then, build the Docker image for the
OpenDissertation backend API with `docker-compose`.

```bash
$ docker-compose build
```

Verify the image was created by running the following in a terminal.

```bash
$ docker image ls
```

### Development

OpenDissertation's API builds upon the OpenAI API and the following link was
referenced during development.
- https://developers.openai.com/api/docs

The development server is started with

```bash
$ docker-compose up -d
```

Responses from the OpenDissertation API that are viewable can be seen at
`http://localhost:8000/api/v1/<api_path>`.

Once you are done with development, shut down the server with

```bash
$ docker-compose down
```

### Production

An `OPENAI_API_KEY` environment variable needs to be defined in the production
environment prior to merging any od_backend branches into main.

The production site can be viewed at https://opendissertation.com.

### Evaluation

We incorporated GPT-5.6 in the multi-turn chat logic, where the user requests it
to read one or more dissertations and answer questions about them. We decided to
use Codex to build the front-end, as we realized that coding in languages other
than Python was our weakness and that Codex could accelerate that aspect of our
hackathon project.

Key decisions included:

- Partitioning the tasks based on access to resources and software engineering
  knowledge. For example,
  - Seong had access to ProQuest through his institution as well as a Chat-GPT
    Plus subscription so he worked on figuring out how to retrieve dissertations
    from universities.
  - Jeffry had more experience setting up APIs in prior hackathons, so he worked
    on setting up the structure of the back-end repo.
- Incorporating the asynchronous OpenAI GPT-5.6 and httpx clients to support
  uploading and processing dissertations with larger file sizes without freezing
  the system.

### Suggestions

Development suggestions can be requested by opening a new ticket at
https://github.com/OpenDissertation/od_backend/issues.
