export function parseAuthorizationContext(user) {
  if (!user || !Array.isArray(user.roles) || !Array.isArray(user.permissions)) {
    return null;
  }

  const roles = [];
  for (const role of user.roles) {
    if (typeof role !== 'string' || !role.trim()) return null;
    roles.push(role.trim().toLowerCase());
  }

  const permissions = [];
  for (const permission of user.permissions) {
    if (typeof permission !== 'string' || !permission || permission !== permission.trim()) {
      return null;
    }
    permissions.push(permission);
  }

  if (new Set(roles).size !== roles.length || new Set(permissions).size !== permissions.length) {
    return null;
  }
  if (roles.length === 0 && permissions.length > 0) {
    return null;
  }

  return { roles, permissions };
}