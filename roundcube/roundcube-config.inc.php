<?php
// mailserver uses a self-signed cert and is only reached over the internal docker network.
$ssl_opts = [
    'ssl' => [
        'verify_peer'       => false,
        'verify_peer_name'  => false,
        'allow_self_signed' => true,
    ],
];
$config['imap_conn_options'] = $ssl_opts;
$config['smtp_conn_options'] = $ssl_opts;
