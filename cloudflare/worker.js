// Cloudflare Worker que lanza el robot de RunningSpain cada día.
// GitHub a veces retrasa o se salta sus horarios; los de Cloudflare son puntuales.
// Necesita un secreto GITHUB_TOKEN (token fine-grained con "Actions: Read and write" en RunningSpain)
// y un Cron Trigger, por ejemplo "17 3 * * *".

const REPO = "alexample/RunningSpain";
const WORKFLOW = "actualizar.yml";

async function launch(env) {
  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "User-Agent": "runningspain-cron",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  const text = res.status === 204 ? "" : await res.text();
  console.log(`GitHub respondió ${res.status} ${text}`);
  if (res.status !== 204) throw new Error(`No se pudo lanzar el robot: ${res.status} ${text}`);
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(launch(env));
  },
  async fetch() {
    return new Response("RunningSpain cron activo. El robot se lanza solo según el Cron Trigger.", {
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  },
};
