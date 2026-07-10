use rmcp::{
    model::{
        ErrorData, ListResourceTemplatesResult, ListResourcesResult, PaginatedRequestParams,
        ReadResourceRequestParams, ReadResourceResult, Resource, ResourceContents,
        ResourceTemplate, ServerCapabilities, ServerInfo,
    },
    service::RequestContext,
    transport::stdio,
    RoleServer, ServerHandler, ServiceExt,
};
use std::{
    collections::VecDeque,
    env, fs,
    path::{Component, Path, PathBuf},
};

const TREE_URI: &str = "ccswitch://project/tree";
const TREE_URI_PREFIX: &str = "ccswitch://project/tree/";
const FILE_URI_PREFIX: &str = "ccswitch://project/file/";
const ROOT_TREE_DEPTH: usize = 2;
const SUBTREE_DEPTH: usize = 4;
const MAX_TREE_ENTRIES: usize = 2000;
const MAX_FILE_BYTES: u64 = 512 * 1024;
const IGNORED_DIRS: &[&str] = &[".git", "node_modules", "target", "dist", "build"];

#[derive(Debug, Clone)]
struct ReadonlyProjectServer {
    root: PathBuf,
}

impl ReadonlyProjectServer {
    fn from_env() -> anyhow::Result<Self> {
        let root = match env::var("CCSWITCH_READONLY_ROOT") {
            Ok(root) if !root.trim().is_empty() => PathBuf::from(root),
            _ => env::current_dir()?,
        };
        let root = fs::canonicalize(root)?;
        if !root.is_dir() {
            anyhow::bail!("readonly MCP root is not a directory");
        }
        Ok(Self { root })
    }

    fn tree_text(&self, uri: &str) -> Result<String, ErrorData> {
        let (base, max_depth) = if uri == TREE_URI {
            (self.root.clone(), ROOT_TREE_DEPTH)
        } else if let Some(rel) = uri.strip_prefix(TREE_URI_PREFIX) {
            (resolve_inside_root(&self.root, rel)?, SUBTREE_DEPTH)
        } else {
            return Err(ErrorData::resource_not_found("resource not found", None));
        };
        if !base.is_dir() {
            return Err(invalid_params("resource is not a directory"));
        }

        let mut out = String::new();
        out.push_str(&format!("root: {}\n", self.root.display()));
        let rel_base = base.strip_prefix(&self.root).unwrap_or(&base);
        let scope = if rel_base.as_os_str().is_empty() {
            ".".to_string()
        } else {
            rel_base.to_string_lossy().to_string()
        };
        out.push_str(&format!("scope: {scope}\n"));

        let mut queue = VecDeque::from([(base, 0usize)]);
        let mut entries_seen = 0usize;
        let mut truncated = false;

        while let Some((dir, depth)) = queue.pop_front() {
            if depth >= max_depth {
                continue;
            }

            let mut entries = fs::read_dir(&dir)
                .map_err(|err| invalid_params(format!("cannot read directory: {err}")))?
                .filter_map(Result::ok)
                .collect::<Vec<_>>();
            entries.sort_by_key(|entry| entry.file_name());

            for entry in entries {
                if entries_seen >= MAX_TREE_ENTRIES {
                    truncated = true;
                    break;
                }

                let name = entry.file_name().to_string_lossy().to_string();
                let path = entry.path();
                let is_dir = path.is_dir();
                if is_dir && IGNORED_DIRS.contains(&name.as_str()) {
                    continue;
                }

                let rel = path.strip_prefix(&self.root).unwrap_or(&path);
                out.push_str(&"  ".repeat(depth));
                out.push_str(&rel.to_string_lossy());
                if is_dir {
                    out.push('/');
                }
                out.push('\n');
                entries_seen += 1;

                if is_dir {
                    queue.push_back((path, depth + 1));
                }
            }

            if truncated {
                break;
            }
        }

        if truncated {
            out.push_str("[truncated: max entries reached]\n");
        }
        Ok(out)
    }

    fn read_file_text(&self, uri: &str) -> Result<String, ErrorData> {
        let rel = uri
            .strip_prefix(FILE_URI_PREFIX)
            .ok_or_else(|| invalid_params("unsupported resource uri"))?;
        let path = resolve_inside_root(&self.root, rel)?;
        if !path.is_file() {
            return Err(invalid_params("resource is not a file"));
        }

        let meta = fs::metadata(&path).map_err(|err| invalid_params(format!("metadata: {err}")))?;
        if meta.len() > MAX_FILE_BYTES {
            return Err(invalid_params("file exceeds 512 KiB limit"));
        }

        let bytes = fs::read(&path).map_err(|err| invalid_params(format!("read file: {err}")))?;
        if bytes.contains(&0) {
            return Err(invalid_params("binary file rejected"));
        }

        String::from_utf8(bytes).map_err(|_| invalid_params("file is not valid UTF-8 text"))
    }
}

impl ServerHandler for ReadonlyProjectServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo::new(ServerCapabilities::builder().enable_resources().build())
    }

    async fn list_resources(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListResourcesResult, ErrorData> {
        Ok(ListResourcesResult {
            resources: vec![Resource::new(TREE_URI, "project-tree")
                .with_description("Read-only project directory tree")
                .with_mime_type("text/plain")],
            next_cursor: None,
            meta: None,
        })
    }

    async fn list_resource_templates(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListResourceTemplatesResult, ErrorData> {
        Ok(ListResourceTemplatesResult {
            resource_templates: vec![
                ResourceTemplate::new("ccswitch://project/tree/{path}", "project-subtree")
                    .with_description("Read a shallow project subtree")
                    .with_mime_type("text/plain"),
                ResourceTemplate::new("ccswitch://project/file/{path}", "project-file")
                    .with_description("Read a UTF-8 project file")
                    .with_mime_type("text/plain"),
            ],
            next_cursor: None,
            meta: None,
        })
    }

    async fn read_resource(
        &self,
        request: ReadResourceRequestParams,
        _context: RequestContext<RoleServer>,
    ) -> Result<ReadResourceResult, ErrorData> {
        let (uri, text) = if request.uri == TREE_URI || request.uri.starts_with(TREE_URI_PREFIX) {
            let uri = request.uri;
            let text = self.tree_text(&uri)?;
            (uri, text)
        } else if request.uri.starts_with(FILE_URI_PREFIX) {
            let text = self.read_file_text(&request.uri)?;
            (request.uri, text)
        } else {
            return Err(ErrorData::resource_not_found("resource not found", None));
        };

        Ok(ReadResourceResult::new(vec![
            ResourceContents::TextResourceContents {
                uri,
                mime_type: Some("text/plain".to_string()),
                text,
                meta: None,
            },
        ]))
    }
}

fn resolve_inside_root(root: &Path, relative: &str) -> Result<PathBuf, ErrorData> {
    let rel = percent_decode(relative)?;
    let path = Path::new(&rel);
    if path.is_absolute()
        || path
            .components()
            .any(|component| matches!(component, Component::ParentDir | Component::Prefix(_)))
    {
        return Err(invalid_params("path must be relative and stay under root"));
    }

    let joined = root.join(path);
    let canonical =
        fs::canonicalize(&joined).map_err(|err| invalid_params(format!("canonicalize: {err}")))?;
    if !canonical.starts_with(root) {
        return Err(invalid_params("path escapes root"));
    }
    Ok(canonical)
}

fn percent_decode(input: &str) -> Result<String, ErrorData> {
    let bytes = input.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0usize;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            if i + 2 >= bytes.len() {
                return Err(invalid_params("invalid percent encoding"));
            }
            let hex = std::str::from_utf8(&bytes[i + 1..i + 3])
                .map_err(|_| invalid_params("invalid percent encoding"))?;
            let value = u8::from_str_radix(hex, 16)
                .map_err(|_| invalid_params("invalid percent encoding"))?;
            out.push(value);
            i += 3;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8(out).map_err(|_| invalid_params("path is not valid UTF-8"))
}

fn invalid_params(message: impl Into<String>) -> ErrorData {
    ErrorData::invalid_params(message.into(), None)
}

pub async fn run_readonly_mcp_async() -> anyhow::Result<()> {
    ReadonlyProjectServer::from_env()?
        .serve(stdio())
        .await?
        .waiting()
        .await?;
    Ok(())
}

pub fn run_readonly_mcp() -> anyhow::Result<()> {
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?
        .block_on(run_readonly_mcp_async())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn readonly_server_uses_current_dir_when_root_env_missing() {
        let temp = TempDir::new().expect("tempdir");
        let old_cwd = env::current_dir().expect("cwd");
        let old_root = env::var("CCSWITCH_READONLY_ROOT").ok();
        env::remove_var("CCSWITCH_READONLY_ROOT");
        env::set_current_dir(temp.path()).expect("set cwd");

        let server = ReadonlyProjectServer::from_env().expect("server");

        env::set_current_dir(old_cwd).expect("restore cwd");
        if let Some(root) = old_root {
            env::set_var("CCSWITCH_READONLY_ROOT", root);
        }
        assert_eq!(
            server.root,
            fs::canonicalize(temp.path()).expect("canonical")
        );
    }
}
