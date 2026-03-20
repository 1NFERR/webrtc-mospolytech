import * as esbuild from "esbuild";
import { config as dotenvConfig } from "dotenv";

dotenvConfig({ path: new URL("../.env", import.meta.url).pathname });

const watch = process.argv.includes("--watch");

const WS_URL = process.env.WS_URL ?? "";

const shared = {
  entryPoints: ["src/main.ts"],
  bundle: true,
  format: "esm",
  target: "es2020",
  outfile: "dist/main.js",
  define: {
    __WS_URL__: JSON.stringify(WS_URL)
  }
};

if (watch) {
  const ctx = await esbuild.context(shared);
  await ctx.watch();
  console.log("watching…");
} else {
  await esbuild.build(shared);
}

