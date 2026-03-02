import { createRemoteJWKSet, jwtVerify } from "jose";

export const createTokenVerifier = ({ jwksUrl, issuer, allowInsecure }) => {
  if (allowInsecure) {
    console.warn("[token] ALLOW_INSECURE_TOKENS is enabled - DO NOT USE IN PROD");
    return async () => ({
      sub: "demo-user",
      preferred_username: "demo",
      client_id: "demo-client",
      realm_access: { roles: ["operator"] },
      resource_access: {},
    });
  }

  if (!jwksUrl || !issuer) {
    throw new Error("KEYCLOAK_JWKS_URL and KEYCLOAK_ISSUER must be provided");
  }

  const jwks = createRemoteJWKSet(new URL(jwksUrl));
  return async (token, audience) => {
    if (!token) {
      throw new Error("Missing bearer token");
    }
    const options = {
      issuer,
    };
    if (audience) {
      options.audience = audience;
    }
    const { payload } = await jwtVerify(token, jwks, options);
    return payload;
  };
};

export const hasRole = (payload, role) => {
  if (!role) {
    return true;
  }
  const realmRoles = payload?.realm_access?.roles || [];
  const clientRoles = Object.values(payload?.resource_access || {}).flatMap(
    (entry) => entry?.roles || []
  );
  return realmRoles.includes(role) || clientRoles.includes(role);
};
