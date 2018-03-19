# Setting up


* gcloud_service.json
* AWS Fargate

This folder contains the code for running the GWA worker on AWS Fargate.

If you cloned the repo you will need to obtain the service credentials from the GCloud console


## Testing


Rebuild and test 
```shell
REPORT_NAME='test-map-private-test'
TRAIT_NAME='telomere-resids'
docker build . -t cegwas-mapping
docker run -v $PWD:/home/linuxbrew/work \
           -w /home/linuxbrew/work \
           -it \
           --rm \
           -e REPORT_NAME=${REPORT_NAME} \
           -e TRAIT_NAME=${TRAIT_NAME} \
           -e GOOGLE_APPLICATION_CREDENTIALS=gcloud_fargate.json \
           -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
           -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY} \
           cegwas-mapping
```

Test
```
docker run -it --rm -e REPORT_NAME='test-report' -e TRAIT_NAME='yeah1' -e GOOGLE_APPLICATION_CREDENTIALS=gcloud_fargate.json  cegwas-mapping
```

## Pushing new versions

```
aws ecr get-login --no-include-email --region us-east-1 | bash
docker build -t cegwas-mapping .
docker tag cegwas-mapping:latest 710251016579.dkr.ecr.us-east-1.amazonaws.com/cegwas-mapping:latest
docker push 710251016579.dkr.ecr.us-east-1.amazonaws.com/cegwas-mapping:latest
```