use std::error::Error;

use omnipaxos::errors::ConfigError;

#[test]
fn invalid_config_error_has_a_finite_source_chain() {
    let error = ConfigError::InvalidConfig("invalid value".to_string());
    let mut current: Option<&dyn Error> = Some(&error);
    let mut chain = Vec::new();
    for _ in 0..16 {
        let Some(item) = current else {
            assert!(!chain.is_empty());
            return;
        };
        chain.push(item.to_string());
        current = item.source();
    }
    panic!("error source chain did not terminate: {:?}", chain);
}
