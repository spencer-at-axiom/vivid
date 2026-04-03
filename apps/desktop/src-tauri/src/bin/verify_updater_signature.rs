use minisign_verify::{PublicKey, Signature};
use serde::Serialize;
use std::env;
use std::error::Error;
use std::ffi::OsString;
use std::fs::{self, File};
use std::io::Read;
use std::path::{Path, PathBuf};

#[derive(Debug)]
struct Args {
    roots: Vec<PathBuf>,
    pubkey: String,
    summary_out: Option<PathBuf>,
}

#[derive(Debug, Serialize)]
struct VerificationRecord {
    artifact_path: String,
    signature_path: String,
    trusted_comment: String,
}

#[derive(Debug, Serialize)]
struct VerificationSummary {
    verified_count: usize,
    records: Vec<VerificationRecord>,
}

#[derive(Debug)]
struct SignaturePair {
    artifact_path: PathBuf,
    signature_path: PathBuf,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("Updater signature verification failed: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn Error>> {
    let args = parse_args(env::args_os().skip(1))?;
    let public_key = parse_public_key(&args.pubkey)?;
    let pairs = discover_signature_pairs(&args.roots)?;

    if pairs.is_empty() {
        return Err("No updater signature files were found under the provided root paths.".into());
    }

    let mut records = Vec::with_capacity(pairs.len());
    for pair in pairs {
        let signature = Signature::from_file(&pair.signature_path)?;
        let mut verifier = public_key.verify_stream(&signature)?;
        let mut artifact = File::open(&pair.artifact_path)?;
        let mut buffer = [0u8; 8192];
        loop {
            let bytes_read = artifact.read(&mut buffer)?;
            if bytes_read == 0 {
                break;
            }
            verifier.update(&buffer[..bytes_read]);
        }
        verifier.finalize()?;

        println!(
            "verified updater artifact: {} ({})",
            pair.artifact_path.display(),
            signature.trusted_comment()
        );
        records.push(VerificationRecord {
            artifact_path: pair.artifact_path.display().to_string(),
            signature_path: pair.signature_path.display().to_string(),
            trusted_comment: signature.trusted_comment().to_string(),
        });
    }

    if let Some(summary_out) = args.summary_out {
        if let Some(parent) = summary_out.parent() {
            fs::create_dir_all(parent)?;
        }
        let payload = serde_json::to_string_pretty(&VerificationSummary {
            verified_count: records.len(),
            records,
        })?;
        fs::write(summary_out, payload)?;
    }

    Ok(())
}

fn parse_args(args: impl Iterator<Item = OsString>) -> Result<Args, Box<dyn Error>> {
    let mut roots = Vec::new();
    let mut pubkey: Option<String> = None;
    let mut summary_out: Option<PathBuf> = None;
    let mut iter = args;

    while let Some(argument) = iter.next() {
        let argument = argument.to_string_lossy().into_owned();
        match argument.as_str() {
            "--root" => {
                let value = iter.next().ok_or("Missing value for --root")?;
                roots.push(PathBuf::from(value));
            }
            "--pubkey" => {
                let value = iter.next().ok_or("Missing value for --pubkey")?;
                pubkey = Some(value.to_string_lossy().into_owned());
            }
            "--pubkey-env" => {
                let value = iter.next().ok_or("Missing value for --pubkey-env")?;
                let env_name = value.to_string_lossy().into_owned();
                let env_value = env::var(&env_name)
                    .map_err(|_| format!("Environment variable '{env_name}' is not set."))?;
                pubkey = Some(env_value);
            }
            "--summary-out" => {
                let value = iter.next().ok_or("Missing value for --summary-out")?;
                summary_out = Some(PathBuf::from(value));
            }
            "--help" | "-h" => {
                print_usage();
                std::process::exit(0);
            }
            unknown => return Err(format!("Unsupported argument '{unknown}'.").into()),
        }
    }

    if roots.is_empty() {
        return Err("At least one --root path is required.".into());
    }

    let pubkey = pubkey.ok_or("Either --pubkey or --pubkey-env is required.")?;
    Ok(Args {
        roots,
        pubkey,
        summary_out,
    })
}

fn print_usage() {
    println!(
        "Usage: verify_updater_signature --root <bundle-dir> [--root <bundle-dir> ...] (--pubkey <value> | --pubkey-env <ENV>) [--summary-out <path>]"
    );
}

fn normalize_multiline_secret(raw: &str) -> String {
    raw.replace("\\n", "\n").trim().to_string()
}

fn parse_public_key(raw: &str) -> Result<PublicKey, Box<dyn Error>> {
    let normalized = normalize_multiline_secret(raw);
    if normalized.contains('\n') || normalized.starts_with("untrusted comment:") {
        Ok(PublicKey::decode(&normalized)?)
    } else {
        Ok(PublicKey::from_base64(&normalized)?)
    }
}

fn discover_signature_pairs(roots: &[PathBuf]) -> Result<Vec<SignaturePair>, Box<dyn Error>> {
    let mut pairs = Vec::new();
    for root in roots {
        if !root.exists() {
            return Err(format!("Root path does not exist: {}", root.display()).into());
        }
        let mut stack = vec![root.clone()];
        while let Some(path) = stack.pop() {
            if path.is_dir() {
                for entry in fs::read_dir(&path)? {
                    let entry = entry?;
                    stack.push(entry.path());
                }
                continue;
            }

            if path.extension().and_then(|value| value.to_str()) != Some("sig") {
                continue;
            }

            let artifact_path = artifact_path_from_signature(&path)?;
            if !artifact_path.exists() {
                return Err(format!(
                    "Signature file does not have a matching artifact: {}",
                    path.display()
                )
                .into());
            }
            pairs.push(SignaturePair {
                artifact_path,
                signature_path: path,
            });
        }
    }

    pairs.sort_by(|left, right| left.artifact_path.cmp(&right.artifact_path));
    Ok(pairs)
}

fn artifact_path_from_signature(signature_path: &Path) -> Result<PathBuf, Box<dyn Error>> {
    let file_name = signature_path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or("Signature path contains an unsupported file name.")?;
    let artifact_name = file_name
        .strip_suffix(".sig")
        .ok_or("Signature file must end with '.sig'.")?;
    Ok(signature_path.with_file_name(artifact_name))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    const PUBLIC_KEY: &str = "untrusted comment: minisign public key E7620F1842B4E81F\nRWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3\n";
    const SIGNATURE: &str = "untrusted comment: signature from minisign secret key\nRUQf6LRCGA9i559r3g7V1qNyJDApGip8MfqcadIgT9CuhV3EMhHoN1mGTkUidF/z7SrlQgXdy8ofjb7bNJJylDOocrCo8KLzZwo=\ntrusted comment: timestamp:1556193335\tfile:test\ny/rUw2y8/hOUYjZU71eHp/Wo1KZ40fGy2VJEDl34XMJM+TX48Ss/17u3IvIfbVR1FkZZSNCisQbuQY+bHwhEBg==\n";

    #[test]
    fn normalizes_escaped_newlines() {
        let raw = "line-one\\nline-two\\n";
        assert_eq!(normalize_multiline_secret(raw), "line-one\nline-two");
    }

    #[test]
    fn verifies_sample_artifact_pair() -> Result<(), Box<dyn Error>> {
        let temp_root = unique_temp_dir();
        fs::create_dir_all(&temp_root)?;
        let artifact_path = temp_root.join("bundle.tar.gz");
        let signature_path = temp_root.join("bundle.tar.gz.sig");
        fs::write(&artifact_path, b"test")?;
        fs::write(&signature_path, SIGNATURE)?;

        let public_key = parse_public_key(PUBLIC_KEY)?;
        let pairs = discover_signature_pairs(&[temp_root.clone()])?;
        assert_eq!(pairs.len(), 1);

        let signature = Signature::from_file(&pairs[0].signature_path)?;
        let mut verifier = public_key.verify_stream(&signature)?;
        verifier.update(b"test");
        verifier.finalize()?;

        fs::remove_dir_all(temp_root)?;
        Ok(())
    }

    fn unique_temp_dir() -> PathBuf {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time before unix epoch")
            .as_nanos();
        env::temp_dir().join(format!("vivid-updater-verify-{timestamp}"))
    }
}
