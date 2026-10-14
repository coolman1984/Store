import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const schemaPath = join(dirname(fileURLToPath(import.meta.url)), '..', 'schema.sql');

function wrapStmt(stmt) {
  return {
    bind(...args) {
      return {
        async run() {
          const info = stmt.run(...args);
          return { meta: { changes: info.changes } };
        },
        async first() {
          return stmt.get(...args) ?? null;
        },
        async all() {
          return { results: stmt.all(...args) };
        },
      };
    },
  };
}

export function newD1() {
  const db = new DatabaseSync(':memory:');
  db.exec(readFileSync(schemaPath, 'utf8'));
  return {
    prepare(sql) {
      return wrapStmt(db.prepare(sql));
    },
    async batch(stmts) {
      db.exec('BEGIN');
      try {
        const results = [];
        for (const s of stmts) {
          results.push(await s.run());
        }
        db.exec('COMMIT');
        return results;
      } catch (e) {
        db.exec('ROLLBACK');
        throw e;
      }
    },
  };
}
