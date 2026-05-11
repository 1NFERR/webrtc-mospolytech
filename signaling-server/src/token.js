import { createRemoteJWKSet, jwtVerify } from "jose";

export const createTokenVerifier = ({ jwksUrl, issuer, allowInsecure }) => {
  if (allowInsecure) {
    // В insecure режиме всё скипаем
    return async (token) => ({
      sub: token,
      client_id: token,
      preffered_username: token,
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
